"""Environment-based web process configuration."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    session_secret: str
    secure_cookies: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        secret = os.environ.get("SPT_SESSION_SECRET", "")
        if len(secret) < 32:
            raise RuntimeError("Defina SPT_SESSION_SECRET com pelo menos 32 caracteres aleatórios.")
        secure = os.environ.get("SPT_SECURE_COOKIES", "true").lower()
        if secure not in {"true", "false"}:
            raise RuntimeError("SPT_SECURE_COOKIES deve ser true ou false.")
        return cls(
            database_path=Path(os.environ.get("SPT_DB_PATH", "data/smart_price_tag.db")),
            session_secret=secret,
            secure_cookies=secure == "true",
        )
