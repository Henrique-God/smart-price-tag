"""Wire format, durable publication, telemetry and broker ACL checks."""

import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from smart_price_tag.catalog import link_product, register_tag, save_product, save_promotion
from smart_price_tag.authentication import create_first_admin
from smart_price_tag.config import Settings
from smart_price_tag.db import Tag, create_tables, make_engine
from smart_price_tag.monitor import InvalidStatus, record_status
from smart_price_tag.publisher import serialize, stage_configs
from smart_price_tag.security import derive_tag_key
from smart_price_tag import security
from smart_price_tag.web import create_app


MASTER = os.urandom(32)  # ephemeral test key; no deployed key enters source control
TAG_A = "A1B2C3D4E5F6"
TAG_B = "112233445566"


def wait_until(predicate, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.05)
    pytest.fail("A condição MQTT esperada não ocorreu.")


def test_exact_data_hmac_version_and_sequence(tmp_path):
    engine = make_engine(tmp_path / "catalog.db")
    create_tables(engine)
    with Session(engine) as session:
        product = save_product(session, product_id=None, name="Café", price="12,90", description="Pacote", ean13="7891234567895")
        register_tag(session, TAG_A)
        link_product(session, TAG_A, product.id)
        assert stage_configs(session, MASTER) == 1
        tag = session.get(Tag, TAG_A)
        envelope = json.loads(tag.pending_payload)
        data = envelope["dados"]
        body = json.loads(data)
        assert body["produto"] == {"nome": "Café", "preco": 1290, "descricao": "Pacote", "ean13": "7891234567895"}
        assert body["promocao"] is None
        assert body["versao"] == hashlib.sha256(serialize({"produto": body["produto"], "promocao": None}).encode()).hexdigest()[:8]
        assert body["seq"] == 1
        assert len(envelope["hmac"]) == 32
        assert envelope["hmac"] == hmac.new(derive_tag_key(MASTER, TAG_A), data.encode(), hashlib.sha256).digest()[:16].hex()
        assert stage_configs(session, MASTER) == 0
        old_version = body["versao"]
        save_product(session, product_id=product.id, name="Café", price="13,00", description="Pacote", ean13="7891234567895")
        assert stage_configs(session, MASTER) == 1
        new_body = json.loads(json.loads(session.get(Tag, TAG_A).pending_payload)["dados"])
        assert new_body["seq"] == 2 and new_body["versao"] != old_version
        expiry = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        save_promotion(session, product.id, "9,99", expiry)
        assert stage_configs(session, MASTER) == 1
        promotion_body = json.loads(json.loads(session.get(Tag, TAG_A).pending_payload)["dados"])
        assert promotion_body["promocao"] == {"preco": 999, "expira_em": int(datetime.strptime(expiry, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc).timestamp())}
        link_product(session, TAG_A, None)
        assert stage_configs(session, MASTER) == 1
        clear_body = json.loads(json.loads(session.get(Tag, TAG_A).pending_payload)["dados"])
        assert clear_body["produto"] is None and clear_body["promocao"] is None and clear_body["seq"] == 4


def test_status_validation_and_old_status_rejected(tmp_path):
    engine = make_engine(tmp_path / "catalog.db")
    create_tables(engine)
    with Session(engine) as session:
        register_tag(session, TAG_A)
        payload = {"versao": "abcdef01", "tensao_mv": 3920, "rssi": -61, "firmware": "1.0.0", "instante": 1790000000}
        assert record_status(session, f"spt/{TAG_A}/status", json.dumps(payload).encode(), received_at=1790000010)
        tag = session.get(Tag, TAG_A)
        assert (tag.confirmed_version, tag.battery_mv, tag.rssi, tag.firmware, tag.last_seen_at) == ("abcdef01", 3920, -61, "1.0.0", 1790000000)
        assert not record_status(session, f"spt/{TAG_A}/status", json.dumps(payload).encode(), received_at=1790000010)
        with pytest.raises(InvalidStatus):
            record_status(session, f"spt/{TAG_B}/status", json.dumps(payload).encode(), received_at=1790000010)
        with pytest.raises(InvalidStatus):
            record_status(session, f"spt/{TAG_A}/status", json.dumps({**payload, "tensao_mv": True}).encode(), received_at=1790000010)


def test_old_confirmation_is_not_reused_when_content_returns(tmp_path):
    engine = make_engine(tmp_path / "catalog.db")
    create_tables(engine)
    with Session(engine) as session:
        product = save_product(session, product_id=None, name="Café", price="12,90", description="Pacote", ean13="7891234567895")
        register_tag(session, TAG_A)
        link_product(session, TAG_A, product.id)
        stage_configs(session, MASTER)
        original = session.get(Tag, TAG_A).desired_version
        instant = int(time.time())
        status = {"versao": original, "tensao_mv": 3900, "rssi": -60, "firmware": "test", "instante": instant}
        record_status(session, f"spt/{TAG_A}/status", json.dumps(status).encode(), received_at=instant)
        save_product(session, product_id=product.id, name="Café", price="13,00", description="Pacote", ean13="7891234567895")
        stage_configs(session, MASTER)
        save_product(session, product_id=product.id, name="Café", price="12,90", description="Pacote", ean13="7891234567895")
        stage_configs(session, MASTER)
        tag = session.get(Tag, TAG_A)
        assert tag.desired_version == tag.confirmed_version == original
        assert tag.sequence == 3 and tag.confirmed_sequence == 1


def test_provision_writes_only_individual_key_outside_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPT_MQTT_MASTER_KEY", MASTER.hex())
    monkeypatch.setattr(security.sys, "argv", ["security", TAG_A])
    security.main()
    assert (tmp_path / "secrets" / f"{TAG_A}.key").read_text().strip() == derive_tag_key(MASTER, TAG_A).hex()
    with pytest.raises(SystemExit):
        security.main()


def find_mosquitto():
    installed = Path("C:/Program Files/mosquitto")
    broker = shutil.which("mosquitto") or installed / "mosquitto.exe"
    passwd = shutil.which("mosquitto_passwd") or installed / "mosquitto_passwd.exe"
    pub = shutil.which("mosquitto_pub") or installed / "mosquitto_pub.exe"
    sub = shutil.which("mosquitto_sub") or installed / "mosquitto_sub.exe"
    if not all(Path(item).is_file() for item in (broker, passwd, pub, sub)):
        pytest.skip("Mosquitto não instalado")
    return tuple(map(str, (broker, passwd, pub, sub)))


def broker_fixture(tmp_path):
    broker, passwd, pub, sub = find_mosquitto()
    password_file = tmp_path / "passwords"
    for index, username in enumerate(("spt-app", TAG_A, TAG_B)):
        subprocess.run([passwd, "-b", *(["-c"] if index == 0 else []), str(password_file), username, "fixture-password"], check=True, capture_output=True)
    acl = tmp_path / "acl"
    acl.write_text(f"user spt-app\ntopic write spt/+/config\ntopic read spt/+/status\nuser {TAG_A}\ntopic read spt/{TAG_A}/config\ntopic write spt/{TAG_A}/status\nuser {TAG_B}\ntopic read spt/{TAG_B}/config\ntopic write spt/{TAG_B}/status\n", encoding="ascii")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = tmp_path / "mosquitto.conf"
    config.write_text(f"listener {port} 127.0.0.1\nallow_anonymous false\npassword_file {password_file.as_posix()}\nacl_file {acl.as_posix()}\npersistence true\npersistence_location {tmp_path.as_posix()}/\n", encoding="ascii")
    process = subprocess.Popen([broker, "-c", str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def ready():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            return False
    wait_until(ready)
    return process, port, broker, pub, sub


def test_mosquitto_acl_retained_reconnect_and_status(tmp_path):
    process, port, broker, pub, sub = broker_fixture(tmp_path)
    try:
        settings = Settings(tmp_path / "catalog.db", "example-test-session-secret-more-than-32-characters", False, "127.0.0.1", port, "spt-app", "fixture-password", MASTER)
        app = create_app(settings)
        with TestClient(app) as client:
            with Session(app.state.engine) as session:
                create_first_admin(session, "admin", "example-test-password-123")
            token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").text).group(1)
            assert client.post("/login", data={"csrf_token": token, "username": "admin", "password": "example-test-password-123"}, follow_redirects=False).status_code == 303
            with Session(app.state.engine) as session:
                product = save_product(session, product_id=None, name="Café", price="12,90", description="Pacote", ean13="7891234567895")
                product_id = product.id
                register_tag(session, TAG_A)
                link_product(session, TAG_A, product_id)
            app.state.mqtt_service.notify_change()

            def published():
                with Session(app.state.engine) as session:
                    tag = session.get(Tag, TAG_A)
                    return tag.published_sequence == tag.sequence and tag.sequence > 0

            wait_until(published)
            assert "Aguardando primeiro estado" in client.get("/etiquetas").text
            assert "Aplicada" not in client.get("/etiquetas").text
            command = [sub, "-h", "127.0.0.1", "-p", str(port), "-u", TAG_A, "-P", "fixture-password", "-t", f"spt/{TAG_A}/config", "-C", "1", "-W", "3"]
            retained = subprocess.run(command, check=True, capture_output=True, text=True, timeout=5)
            body = json.loads(json.loads(retained.stdout)["dados"])
            assert body["produto"]["preco"] == 1290

            # Broker rejects a tag publishing another tag's configuration.
            unauthorized = subprocess.run([pub, "-V", "mqttv5", "-h", "127.0.0.1", "-p", str(port), "-u", TAG_A, "-P", "fixture-password", "-t", f"spt/{TAG_B}/config", "-m", "bad", "-q", "1"], capture_output=True, timeout=5)
            assert b"Not authorized" in unauthorized.stderr
            own_config_write = subprocess.run([pub, "-V", "mqttv5", "-h", "127.0.0.1", "-p", str(port), "-u", TAG_A, "-P", "fixture-password", "-t", f"spt/{TAG_A}/config", "-m", "bad", "-q", "1"], capture_output=True, timeout=5)
            assert b"Not authorized" in own_config_write.stderr
            other_status_write = subprocess.run([pub, "-V", "mqttv5", "-h", "127.0.0.1", "-p", str(port), "-u", TAG_A, "-P", "fixture-password", "-t", f"spt/{TAG_B}/status", "-m", "bad", "-q", "1"], capture_output=True, timeout=5)
            assert b"Not authorized" in other_status_write.stderr
            subprocess.run([pub, "-h", "127.0.0.1", "-p", str(port), "-u", "spt-app", "-P", "fixture-password", "-t", f"spt/{TAG_B}/config", "-m", "fixture-b", "-r", "-q", "1"], check=True, capture_output=True, timeout=5)
            forbidden_read = subprocess.run([sub, "-V", "mqttv5", "-h", "127.0.0.1", "-p", str(port), "-u", TAG_A, "-P", "fixture-password", "-t", f"spt/{TAG_B}/config", "-C", "1", "-W", "1"], capture_output=True, timeout=5)
            assert forbidden_read.returncode != 0 and not forbidden_read.stdout
            allowed_read = subprocess.run([sub, "-h", "127.0.0.1", "-p", str(port), "-u", TAG_B, "-P", "fixture-password", "-t", f"spt/{TAG_B}/config", "-C", "1", "-W", "1"], check=True, capture_output=True, timeout=5)
            assert allowed_read.stdout.strip() == b"fixture-b"
            anonymous = subprocess.run([sub, "-h", "127.0.0.1", "-p", str(port), "-t", f"spt/{TAG_A}/config", "-C", "1", "-W", "1"], capture_output=True, timeout=5)
            assert anonymous.returncode != 0

            status = json.dumps({"versao": body["versao"], "tensao_mv": 3900, "rssi": -60, "firmware": "test-fixture", "instante": int(time.time())})
            subprocess.run([pub, "-h", "127.0.0.1", "-p", str(port), "-u", TAG_A, "-P", "fixture-password", "-t", f"spt/{TAG_A}/status", "-m", status, "-q", "1"], check=True, capture_output=True, timeout=5)
            def confirmed():
                with Session(app.state.engine) as session:
                    return session.get(Tag, TAG_A).confirmed_version == body["versao"]
            wait_until(confirmed)
            assert "Aplicada" in client.get("/etiquetas").text

            process.terminate()
            process.wait(timeout=5)
            wait_until(lambda: not app.state.mqtt_service.connected.is_set())
            with Session(app.state.engine) as session:
                save_product(session, product_id=product_id, name="Café", price="13,00", description="Pacote", ean13="7891234567895")
            app.state.mqtt_service.notify_change()
            with Session(app.state.engine) as session:
                tag = session.get(Tag, TAG_A)
                assert tag.published_sequence < tag.sequence and tag.confirmed_version == body["versao"] and tag.confirmed_sequence < tag.sequence
            assert "Publicação pendente" in client.get("/etiquetas").text
            process = subprocess.Popen([broker, "-c", str(tmp_path / "mosquitto.conf")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_until(published)
            assert "Estado recebido · aguardando confirmação" in client.get("/etiquetas").text
            retained = subprocess.run(command, check=True, capture_output=True, text=True, timeout=5)
            assert json.loads(json.loads(retained.stdout)["dados"])["produto"]["preco"] == 1300

            # A MQTT 5 PUBACK denial must not be recorded as publication.
            process.terminate()
            process.wait(timeout=5)
            wait_until(lambda: not app.state.mqtt_service.connected.is_set())
            acl_file = tmp_path / "acl"
            acl_file.write_text(acl_file.read_text(encoding="ascii").replace("topic write spt/+/config\n", ""), encoding="ascii")
            process = subprocess.Popen([broker, "-c", str(tmp_path / "mosquitto.conf")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_until(lambda: app.state.mqtt_service.connected.is_set())
            with Session(app.state.engine) as session:
                save_product(session, product_id=product_id, name="Café", price="14,00", description="Pacote", ean13="7891234567895")
            app.state.mqtt_service.notify_change()
            time.sleep(0.6)
            with Session(app.state.engine) as session:
                tag = session.get(Tag, TAG_A)
                assert tag.published_sequence < tag.sequence
            assert "Publicação pendente" in client.get("/etiquetas").text
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
