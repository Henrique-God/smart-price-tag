"""Long-lived MQTT connection and durable retained publication worker."""

import logging
import threading

import paho.mqtt.client as mqtt
from sqlmodel import Session, select

from .config import Settings
from .db import Tag
from .monitor import InvalidStatus, record_status
from .publisher import mark_published, stage_configs


logger = logging.getLogger(__name__)


class MqttService:
    def __init__(self, engine, settings: Settings):
        self.engine = engine
        self.settings = settings
        self.connected = threading.Event()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.stage_lock = threading.Lock()
        self.epoch = 0
        self.sent_epoch: dict[str, int] = {}
        self.publish_results: dict[int, bool] = {}
        self.publish_lock = threading.Lock()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="spt-web", protocol=mqtt.MQTTv5)
        self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_publish = self._on_publish
        self.worker: threading.Thread | None = None

    def start(self) -> None:
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=30, clean_start=True)
        self.client.loop_start()
        self.worker = threading.Thread(target=self._run, daemon=True, name="spt-mqtt-publisher")
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake.set()
        if self.worker is not None:
            self.worker.join(timeout=7)
        self.client.disconnect()
        self.client.loop_stop()

    def notify_change(self) -> None:
        with self.stage_lock, Session(self.engine) as session:
            stage_configs(session, self.settings.mqtt_master_key)
        self.wake.set()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.warning("Conexão MQTT recusada: %s", reason_code)
            return
        result, _mid = client.subscribe("spt/+/status", qos=1)
        if result != mqtt.MQTT_ERR_SUCCESS:
            logger.error("Falha ao assinar estados MQTT: %s", result)
            return
        self.epoch += 1
        self.connected.set()
        self.wake.set()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected.clear()
        with self.publish_lock:
            self.publish_results.clear()
        self.wake.set()

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        with self.publish_lock:
            self.publish_results[mid] = not reason_code.is_failure

    def _on_message(self, client, userdata, message):
        try:
            with Session(self.engine) as session:
                record_status(session, message.topic, message.payload)
        except InvalidStatus as error:
            logger.warning("Estado MQTT ignorado em %s: %s", message.topic, error)
        except Exception:
            logger.exception("Falha ao gravar estado MQTT")

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                with self.stage_lock, Session(self.engine) as session:
                    stage_configs(session, self.settings.mqtt_master_key)
                with Session(self.engine) as session:
                    if self.connected.is_set():
                        for tag in session.exec(select(Tag).order_by(Tag.identifier)).all():
                            if self.stop_event.is_set() or not self.connected.is_set():
                                break
                            if not tag.pending_payload or (tag.published_sequence == tag.sequence and self.sent_epoch.get(tag.identifier) == self.epoch):
                                continue
                            epoch = self.epoch
                            info = self.client.publish(f"spt/{tag.identifier}/config", tag.pending_payload, qos=1, retain=True)
                            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                                break
                            info.wait_for_publish(timeout=5)
                            with self.publish_lock:
                                accepted = self.publish_results.pop(info.mid, False)
                            if not info.is_published() or not accepted or not self.connected.is_set() or epoch != self.epoch:
                                break
                            mark_published(session, tag.identifier, tag.sequence, tag.desired_version)
                            self.sent_epoch[tag.identifier] = epoch
            except Exception:
                logger.exception("Falha no publicador MQTT; tentativa será repetida")
            self.wake.wait(timeout=2)
            self.wake.clear()
