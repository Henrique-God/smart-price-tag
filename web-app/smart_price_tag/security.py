"""Per-tag message authentication. The master key never enters the database."""

import hashlib
import hmac
import os
import re
import sys
from pathlib import Path


def derive_tag_key(master_key: bytes, identifier: str) -> bytes:
    if len(master_key) != 32 or not re.fullmatch(r"[0-9A-F]{12}", identifier):
        raise ValueError("Chave mestra ou identificador inválido.")
    return hmac.new(master_key, identifier.encode("ascii"), hashlib.sha256).digest()


def sign_data(master_key: bytes, identifier: str, data: str) -> str:
    digest = hmac.new(derive_tag_key(master_key, identifier), data.encode("utf-8"), hashlib.sha256).digest()
    return digest[:16].hex()


def main() -> None:
    if len(sys.argv) != 2 or not re.fullmatch(r"[0-9A-F]{12}", sys.argv[1]):
        raise SystemExit("Uso: python -m smart_price_tag.security ID_MAC_EM_MAIUSCULAS")
    try:
        master_key = bytes.fromhex(os.environ["SPT_MQTT_MASTER_KEY"])
        tag_key = derive_tag_key(master_key, sys.argv[1])
    except (KeyError, ValueError) as error:
        raise SystemExit("Defina SPT_MQTT_MASTER_KEY com 32 bytes hexadecimais.") from error
    directory = Path("secrets")
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / f"{sys.argv[1]}.key"
    try:
        with target.open("x", encoding="ascii") as file:
            file.write(tag_key.hex() + "\n")
    except FileExistsError as error:
        raise SystemExit(f"A chave {target} já existe; nenhuma alteração foi feita.") from error
    os.chmod(target, 0o600)
    print(f"Chave individual gravada em {target}; entregue apenas à etiqueta correspondente.")


if __name__ == "__main__":
    main()
