"""Administrator credentials; only bcrypt hashes are stored."""

import getpass
import os
import re
from pathlib import Path

import bcrypt
from sqlmodel import Session, select

from .db import AdminUser


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password.encode("utf-8")) > 72:
        raise ValueError("A senha deve ter entre 12 caracteres e 72 bytes UTF-8.")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def authenticate(session: Session, username: str, password: str) -> AdminUser | None:
    user = session.exec(select(AdminUser).where(AdminUser.username == username)).first()
    if user is None:
        return None
    try:
        valid = bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("ascii"))
    except (ValueError, UnicodeError):
        return None
    return user if valid else None


def create_first_admin(session: Session, username: str, password: str) -> AdminUser:
    if session.exec(select(AdminUser.id)).first() is not None:
        raise ValueError("Já existe um administrador; o comando inicial não pode ser repetido.")
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,80}", username):
        raise ValueError("O login deve ter de 3 a 80 caracteres: letras, números, _, . ou -.")
    user = AdminUser(username=username, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def main() -> None:
    from .db import create_tables, make_engine

    # Local bootstrap does not require the web server's session signing key.
    engine = make_engine(Path(os.environ.get("SPT_DB_PATH", "data/smart_price_tag.db")))
    create_tables(engine)
    with Session(engine) as session:
        if session.exec(select(AdminUser.id)).first() is not None:
            raise SystemExit("Já existe um administrador; nenhuma alteração foi feita.")
        username = input("Login do primeiro administrador: ")
        password = getpass.getpass("Senha (mínimo 12 caracteres): ")
        confirmation = getpass.getpass("Confirme a senha: ")
        if password != confirmation:
            raise SystemExit("As senhas não coincidem; nenhuma alteração foi feita.")
        try:
            create_first_admin(session, username, password)
        except ValueError as error:
            raise SystemExit(str(error)) from error
    print("Administrador criado.")


if __name__ == "__main__":
    main()
