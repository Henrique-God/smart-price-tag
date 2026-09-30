"""Validate and persist telemetry received on each tag's status topic."""

import json
import re
import time

from sqlmodel import Session

from .db import Tag


class InvalidStatus(ValueError):
    pass


def record_status(session: Session, topic: str, payload: bytes, *, received_at: int | None = None) -> bool:
    match = re.fullmatch(r"spt/([0-9A-F]{12})/status", topic)
    if not match or len(payload) > 2048:
        raise InvalidStatus("Tópico ou tamanho de estado inválido.")
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidStatus("JSON de estado inválido.") from error
    if not isinstance(data, dict) or set(data) != {"versao", "tensao_mv", "rssi", "firmware", "instante"}:
        raise InvalidStatus("Campos de estado inválidos.")
    version, battery, rssi, firmware, instant = (data[key] for key in ("versao", "tensao_mv", "rssi", "firmware", "instante"))
    received_at = int(time.time()) if received_at is None else received_at
    if not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{8}", version):
        raise InvalidStatus("Versão inválida.")
    if type(battery) is not int or not 0 <= battery <= 6000 or type(rssi) is not int or not -127 <= rssi <= 0:
        raise InvalidStatus("Bateria ou RSSI inválido.")
    if not isinstance(firmware, str) or not 1 <= len(firmware) <= 64 or any(ord(char) < 32 for char in firmware):
        raise InvalidStatus("Firmware inválido.")
    if type(instant) is not int or not 1577836800 <= instant <= received_at + 300:
        raise InvalidStatus("Instante inválido.")
    tag = session.get(Tag, match.group(1))
    if tag is None:
        raise InvalidStatus("Etiqueta desconhecida.")
    if tag.last_seen_at is not None and instant <= tag.last_seen_at:
        return False
    tag.confirmed_version = version
    if version == tag.desired_version:
        tag.confirmed_sequence = tag.sequence
    tag.battery_mv = battery
    tag.rssi = rssi
    tag.firmware = firmware
    tag.last_seen_at = instant
    tag.last_received_at = received_at
    session.add(tag)
    session.commit()
    return True
