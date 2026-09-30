"""Environment-based web process configuration."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    session_secret: str
    secure_cookies: bool = True
    mqtt_host: str | None = None
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_master_key: bytes | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        secret = os.environ.get("SPT_SESSION_SECRET", "")
        if len(secret) < 32:
            raise RuntimeError("Defina SPT_SESSION_SECRET com pelo menos 32 caracteres aleatórios.")
        secure = os.environ.get("SPT_SECURE_COOKIES", "true").lower()
        if secure not in {"true", "false"}:
            raise RuntimeError("SPT_SECURE_COOKIES deve ser true ou false.")
        host = os.environ.get("SPT_MQTT_HOST")
        username = os.environ.get("SPT_MQTT_USERNAME")
        password = os.environ.get("SPT_MQTT_PASSWORD")
        key_hex = os.environ.get("SPT_MQTT_MASTER_KEY")
        if any((host, username, password, key_hex)) and not all((host, username, password, key_hex)):
            raise RuntimeError("Defina SPT_MQTT_HOST, SPT_MQTT_USERNAME, SPT_MQTT_PASSWORD e SPT_MQTT_MASTER_KEY juntos.")
        try:
            key = bytes.fromhex(key_hex) if key_hex else None
            port = int(os.environ.get("SPT_MQTT_PORT", "1883"))
        except ValueError as error:
            raise RuntimeError("Chave MQTT hexadecimal ou porta MQTT inválida.") from error
        if key is not None and len(key) != 32:
            raise RuntimeError("SPT_MQTT_MASTER_KEY deve conter 32 bytes em hexadecimal.")
        if not 1 <= port <= 65535:
            raise RuntimeError("SPT_MQTT_PORT inválida.")
        return cls(
            database_path=Path(os.environ.get("SPT_DB_PATH", "data/smart_price_tag.db")),
            session_secret=secret,
            secure_cookies=secure == "true",
            mqtt_host=host,
            mqtt_port=port,
            mqtt_username=username,
            mqtt_password=password,
            mqtt_master_key=key,
        )
