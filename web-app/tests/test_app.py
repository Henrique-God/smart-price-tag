import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from smart_price_tag.authentication import create_first_admin
from smart_price_tag.catalog import format_price
from smart_price_tag.config import Settings
from smart_price_tag.db import AdminUser, Product, Tag
from smart_price_tag.web import create_app


TEST_PASSWORD = "example-test-password-123"
TEST_SESSION_SECRET = "example-test-session-secret-more-than-32-characters"


@pytest.fixture
def client_and_app(tmp_path):
    app = create_app(Settings(tmp_path / "catalog.db", TEST_SESSION_SECRET, False))
    with TestClient(app) as client:
        yield client, app


def csrf_token(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)


def log_in(client):
    token = csrf_token(client, "/login")
    response = client.post("/login", data={"csrf_token": token, "username": "admin", "password": TEST_PASSWORD}, follow_redirects=False)
    assert response.status_code == 303


def add_admin(app):
    with Session(app.state.engine) as session:
        create_first_admin(session, "admin", TEST_PASSWORD)


def post_with_csrf(client, path, data, form_page="/produtos"):
    return client.post(path, data={"csrf_token": csrf_token(client, form_page), **data}, follow_redirects=False)


def sample_product(**overrides):
    return {"name": "Café", "price": "12,90", "description": "Pacote 500 g", "ean13": "7891234567895", **overrides}


def test_first_admin_bcrypt_login_logout_and_route_protection(client_and_app):
    client, app = client_and_app
    assert client.get("/produtos", follow_redirects=False).headers["location"] == "/login"
    assert client.post("/produtos/novo", data=sample_product(), follow_redirects=False).status_code == 303
    add_admin(app)
    with Session(app.state.engine) as session:
        user = session.exec(select(AdminUser)).one()
        assert user.password_hash != TEST_PASSWORD
        assert bcrypt.checkpw(TEST_PASSWORD.encode(), user.password_hash.encode())
        with pytest.raises(ValueError):
            create_first_admin(session, "another", "another-example-password-123")
    token = csrf_token(client, "/login")
    failed = client.post("/login", data={"csrf_token": token, "username": "admin", "password": "wrong"})
    assert failed.status_code == 400
    assert "Login ou senha inválidos" in failed.text
    log_in(client)
    assert client.get("/produtos").status_code == 200
    assert client.post("/logout", data={"csrf_token": "invalid"}).status_code == 403
    logout_response = post_with_csrf(client, "/logout", {})
    assert logout_response.status_code == 303
    assert client.get("/produtos", follow_redirects=False).headers["location"] == "/login"


def test_product_validation_crud_and_restart_persistence(client_and_app):
    client, app = client_and_app
    add_admin(app)
    log_in(client)
    assert client.post("/produtos/novo", data=sample_product()).status_code == 403
    invalid = post_with_csrf(client, "/produtos/novo", sample_product(ean13="7891234567890"), "/produtos/novo")
    assert invalid.status_code == 400
    assert "verificador" in invalid.text
    invalid = post_with_csrf(client, "/produtos/novo", sample_product(price="12,999"), "/produtos/novo")
    assert invalid.status_code == 400
    assert post_with_csrf(client, "/produtos/novo", sample_product(), "/produtos/novo").status_code == 303
    with Session(app.state.engine) as session:
        product = session.exec(select(Product)).one()
        product_id = product.id
        assert product.price_cents == 1290
        assert product.ean13 == "7891234567895"
    duplicate = post_with_csrf(client, "/produtos/novo", sample_product(), "/produtos/novo")
    assert duplicate.status_code == 400
    assert "Já existe" in duplicate.text
    updated = post_with_csrf(client, f"/produtos/{product_id}/editar", sample_product(name="Café premium", price="13.20"), f"/produtos/{product_id}/editar")
    assert updated.status_code == 303
    with Session(app.state.engine) as session:
        assert session.get(Product, product_id).price_cents == 1320
    restarted_app = create_app(Settings(Path(app.state.engine.url.database), "another-test-session-secret-more-than-32-characters", False))
    with Session(restarted_app.state.engine) as session:
        assert session.get(Product, product_id).name == "Café premium"
    assert "Café premium" in client.get("/produtos").text
    assert post_with_csrf(client, f"/produtos/{product_id}/excluir", {}).status_code == 303
    with Session(app.state.engine) as session:
        assert session.get(Product, product_id) is None
    assert format_price(1320) == "13,20"


def test_tags_links_and_utc_promotions(client_and_app):
    client, app = client_and_app
    add_admin(app)
    log_in(client)
    post_with_csrf(client, "/produtos/novo", sample_product(), "/produtos/novo")
    with Session(app.state.engine) as session:
        product_id = session.exec(select(Product.id)).one()
    assert post_with_csrf(client, "/etiquetas", {"identifier": "A1:B2:C3:D4:E5:F6"}, "/etiquetas").status_code == 303
    assert post_with_csrf(client, "/etiquetas", {"identifier": "etiqueta-1"}, "/etiquetas").status_code == 400
    duplicate = post_with_csrf(client, "/etiquetas", {"identifier": "a1b2c3d4e5f6"}, "/etiquetas")
    assert duplicate.status_code == 400
    identifier = "A1B2C3D4E5F6"
    with Session(app.state.engine) as session:
        assert session.get(Tag, identifier).product_id is None
    assert post_with_csrf(client, f"/etiquetas/{identifier}/vinculo", {"product_id": str(product_id)}, "/etiquetas").status_code == 303
    with Session(app.state.engine) as session:
        assert session.get(Tag, identifier).product_id == product_id
    assert post_with_csrf(client, f"/etiquetas/{identifier}/vinculo", {"product_id": "999999"}, "/etiquetas").status_code == 303
    with Session(app.state.engine) as session:
        assert session.get(Tag, identifier).product_id == product_id
    assert post_with_csrf(client, f"/produtos/{product_id}/excluir", {}).status_code == 303
    with Session(app.state.engine) as session:
        assert session.get(Product, product_id) is not None
    future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    promotion = post_with_csrf(client, f"/produtos/{product_id}/promocao", {"price": "9,99", "ends_at": future}, f"/produtos/{product_id}/promocao")
    assert promotion.status_code == 303
    with Session(app.state.engine) as session:
        product = session.get(Product, product_id)
        assert product.promotion_price_cents == 999
        assert product.promotion_ends_at == int(datetime.strptime(future, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc).timestamp())
    assert post_with_csrf(client, f"/produtos/{product_id}/promocao", {"price": "8,50", "ends_at": future}, f"/produtos/{product_id}/promocao").status_code == 303
    with Session(app.state.engine) as session:
        assert session.get(Product, product_id).promotion_price_cents == 850
    invalid = post_with_csrf(client, f"/produtos/{product_id}/promocao", {"price": "15,00", "ends_at": future}, f"/produtos/{product_id}/promocao")
    assert invalid.status_code == 400
    invalid = post_with_csrf(client, f"/produtos/{product_id}/promocao", {"price": "8,00", "ends_at": "2020-01-01T00:00"}, f"/produtos/{product_id}/promocao")
    assert invalid.status_code == 400
    assert post_with_csrf(client, f"/produtos/{product_id}/promocao/remover", {}).status_code == 303
    with Session(app.state.engine) as session:
        assert session.get(Product, product_id).promotion_price_cents is None
    assert post_with_csrf(client, f"/etiquetas/{identifier}/vinculo", {"product_id": ""}, "/etiquetas").status_code == 303
    assert post_with_csrf(client, f"/produtos/{product_id}/excluir", {}).status_code == 303
    with Session(app.state.engine) as session:
        assert session.get(Product, product_id) is None
        assert session.get(Tag, identifier).product_id is None


def test_existing_portuguese_sqlite_schema_remains_readable(tmp_path):
    database_path = tmp_path / "existing.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE usuario (id INTEGER PRIMARY KEY, login VARCHAR(80) NOT NULL UNIQUE, senha_hash VARCHAR(100) NOT NULL);
            CREATE TABLE produto (id INTEGER PRIMARY KEY, nome VARCHAR(120) NOT NULL,
                preco_centavos INTEGER NOT NULL, descricao VARCHAR(160) NOT NULL, ean13 VARCHAR(13) NOT NULL UNIQUE,
                promocao_preco_centavos INTEGER, promocao_expira_em INTEGER);
            CREATE TABLE etiqueta (identificador VARCHAR(12) PRIMARY KEY, produto_id INTEGER REFERENCES produto(id));
            INSERT INTO produto (id, nome, preco_centavos, descricao, ean13)
                VALUES (1, 'Produto existente', 1200, 'Descrição existente', '7891234567895');
            INSERT INTO etiqueta (identificador, produto_id) VALUES ('A1B2C3D4E5F6', 1);
            """
        )
    app = create_app(Settings(database_path, TEST_SESSION_SECRET, False))
    with Session(app.state.engine) as session:
        assert session.get(Product, 1).name == "Produto existente"
        assert session.get(Tag, "A1B2C3D4E5F6").product_id == 1
