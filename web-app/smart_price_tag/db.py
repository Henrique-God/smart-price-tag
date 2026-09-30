"""SQLModel entities and SQLite access.

Database table and column names retain the original schema so existing local
catalogs remain readable after Python identifiers move to English.
"""

from pathlib import Path

from sqlalchemy import Column, ForeignKey, Integer, String, event
from sqlmodel import Field, SQLModel, Session, create_engine


class AdminUser(SQLModel, table=True):
    __tablename__ = "usuario"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(sa_column=Column("login", String(80), unique=True, index=True, nullable=False))
    password_hash: str = Field(sa_column=Column("senha_hash", String(100), nullable=False))


class Product(SQLModel, table=True):
    __tablename__ = "produto"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column("nome", String(120), nullable=False))
    price_cents: int = Field(sa_column=Column("preco_centavos", Integer, nullable=False))
    description: str = Field(sa_column=Column("descricao", String(160), nullable=False))
    ean13: str = Field(sa_column=Column("ean13", String(13), unique=True, index=True, nullable=False))
    promotion_price_cents: int | None = Field(default=None, sa_column=Column("promocao_preco_centavos", Integer, nullable=True))
    promotion_ends_at: int | None = Field(default=None, sa_column=Column("promocao_expira_em", Integer, nullable=True))


class Tag(SQLModel, table=True):
    __tablename__ = "etiqueta"

    identifier: str = Field(sa_column=Column("identificador", String(12), primary_key=True))
    product_id: int | None = Field(default=None, sa_column=Column("produto_id", Integer, ForeignKey("produto.id"), nullable=True, index=True))


def make_engine(path: Path):
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def create_tables(engine) -> None:
    SQLModel.metadata.create_all(engine)


def session_for(engine) -> Session:
    return Session(engine)
