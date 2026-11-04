"""Publication history, message presentation and tag status presentation."""

import json
import re
import socket
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlmodel import Session, select

from smart_price_tag.authentication import create_first_admin
from smart_price_tag.catalog import link_product, register_tag, save_product
from smart_price_tag.config import Settings
from smart_price_tag.db import Product, Publication, Tag, create_tables, make_engine
from smart_price_tag.monitor import record_rejected_status, record_status
from smart_price_tag.presentation import (
    battery_status,
    contact_status,
    describe_changes,
    group_hex,
    local_timestamp,
    relative_time,
    rssi_quality,
)
from smart_price_tag.publisher import mark_published, stage_configs
from smart_price_tag.security import sign_data
from smart_price_tag.web import create_app


MASTER = bytes(range(32))  # synthetic test key
TAG = "A1B2C3D4E5F6"
PASSWORD = "example-test-password-123"
SESSION_SECRET = "example-test-session-secret-more-than-32-characters"


def closed_port() -> int:
    """A local port with nothing listening: MQTT stays disconnected, staging still runs."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def mqtt_client(tmp_path):
    settings = Settings(tmp_path / "catalog.db", SESSION_SECRET, False, "127.0.0.1", closed_port(), "spt-app", "fixture-password", MASTER)
    app = create_app(settings)
    with TestClient(app) as client:
        with Session(app.state.engine) as session:
            create_first_admin(session, "admin", PASSWORD)
        token = csrf(client, "/login")
        assert client.post("/login", data={"csrf_token": token, "username": "admin", "password": PASSWORD}, follow_redirects=False).status_code == 303
        yield client, app


def csrf(client, path):
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text).group(1)


def post(client, path, data, page="/produtos"):
    return client.post(path, data={"csrf_token": csrf(client, page), **data}, follow_redirects=False)


def history(app, identifier=TAG):
    with Session(app.state.engine) as session:
        return session.exec(select(Publication).where(Publication.identifier == identifier).order_by(Publication.id)).all()


def feed(client, identifier=TAG):
    return next(item for item in client.get("/mqtt/estado").json()["tags"] if item["identifier"] == identifier)


def test_catalog_changes_record_history_with_reason_and_link_tags(mqtt_client):
    client, app = mqtt_client
    assert post(client, "/produtos/novo", {"name": "Café", "price": "9,90", "description": "Pacote 500 g", "ean13": "7891234567895"}, "/produtos/novo").status_code == 303
    with Session(app.state.engine) as session:
        product_id = session.exec(select(Product.id)).one()

    post(client, "/etiquetas", {"identifier": TAG}, "/etiquetas")
    post(client, f"/etiquetas/{TAG}/vinculo", {"product_id": str(product_id)}, "/etiquetas")
    edited = post(client, f"/produtos/{product_id}/editar", {"name": "Café", "price": "8,50", "description": "Pacote 500 g", "ean13": "7891234567895"}, f"/produtos/{product_id}/editar")
    assert edited.status_code == 303

    # The confirmation lists the affected tag with its new seq and version, linking to its panel.
    page = client.get("/produtos").text
    assert f'href="/etiquetas#tag-{TAG}"' in page and "seq #3" in page and "nova" in page

    future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    post(client, f"/produtos/{product_id}/promocao", {"price": "7,00", "ends_at": future}, f"/produtos/{product_id}/promocao")
    post(client, f"/produtos/{product_id}/promocao/remover", {})
    post(client, f"/etiquetas/{TAG}/vinculo", {"product_id": ""}, "/etiquetas")

    rows = history(app)
    assert [(row.sequence, row.reason) for row in rows] == [
        (1, "cadastro"), (2, "vinculo"), (3, "produto"), (4, "promocao"), (5, "promocao"), (6, "vinculo"),
    ]
    for row in rows:
        body = json.loads(row.data)
        assert body["seq"] == row.sequence and body["versao"] == row.version
        assert row.hmac == sign_data(MASTER, TAG, row.data)
        assert row.published_at is None  # no broker in this test
    with Session(app.state.engine) as session:
        tag = session.get(Tag, TAG)
        assert json.loads(tag.pending_payload) == {"dados": rows[-1].data, "hmac": rows[-1].hmac}

    # Saving the same content keeps the seq and creates no row.
    post(client, f"/etiquetas/{TAG}/vinculo", {"product_id": ""}, "/etiquetas")
    assert len(history(app)) == 6
    assert "sem mudança" in client.get("/etiquetas").text

    item = feed(client)
    assert [entry["seq"] for entry in item["history"]] == [6, 5, 4, 3, 2, 1]
    assert "preço R$ 9,90 → R$ 8,50" in item["history"][3]["changes"]
    assert "promoção criada: R$ 7,00" in item["history"][2]["changes"]
    assert item["history"][1]["changes"] == ["promoção removida"]
    assert item["history"][0]["changes"] == ["produto desvinculado (etiqueta limpa)"]
    assert item["history"][0]["published"] == "Aguardando ACK do broker"
    assert item["history"][1]["published"] == "Não enviada: substituída pela seguinte"


def test_displayed_message_matches_signature_of_exact_data(mqtt_client):
    client, app = mqtt_client
    with Session(app.state.engine) as session:
        product = save_product(session, product_id=None, name="Café Pilão", price="24,90", description="torrado e moído", ean13="7896089012453")
        register_tag(session, TAG)
        link_product(session, TAG, product.id)
    app.state.mqtt_service.notify_change("vinculo")

    item = feed(client)
    expected = sign_data(MASTER, TAG, item["pub_data"])
    assert item["pub_hmac"].replace(" ", "") == expected
    assert item["pub_hmac"] == group_hex(expected)
    assert item["pub_seq"] == "seq #1" and item["pub_topic"] == f"spt/{TAG}/config"
    assert item["pub_reason"] == "Vínculo"
    assert item["pub_name"] == "Café Pilão" and item["pub_price"] == "R$ 24,90"
    assert json.loads(item["pub_data"])["produto"]["nome"] == "Café Pilão"

    page = client.get("/etiquetas").text
    assert group_hex(expected) in page
    assert "Última mensagem enviada" in page
    # The raw view shows the exact signed string (HTML-escaped by Jinja).
    assert item["pub_data"].replace('"', "&#34;") in page
    # Only data and hmac travel on the broker: the tag key and master key never reach the page.
    assert MASTER.hex() not in page and MASTER.hex() not in json.dumps(item)


def test_republication_keeps_seq_and_records_resend_time(tmp_path):
    engine = make_engine(tmp_path / "catalog.db")
    create_tables(engine)
    with Session(engine) as session:
        product = save_product(session, product_id=None, name="Café", price="12,90", description="Pacote", ean13="7891234567895")
        register_tag(session, TAG)
        link_product(session, TAG, product.id)
        stage_configs(session, MASTER, reason="vinculo", now=1_000)
        tag = session.get(Tag, TAG)
        sequence, version = tag.sequence, tag.desired_version

        mark_published(session, TAG, sequence, version, topic=f"spt/{TAG.lower()}/config", now=1_010)
        mark_published(session, TAG, sequence, version, topic=f"spt/{TAG.lower()}/config", now=1_500)
        assert stage_configs(session, MASTER) == 0

        rows = session.exec(select(Publication)).all()
        assert len(rows) == 1
        row = rows[0]
        assert (row.sequence, row.prepared_at, row.published_at, row.republished_at) == (sequence, 1_000, 1_010, 1_500)
        assert row.topic == f"spt/{TAG.lower()}/config"
        assert session.get(Tag, TAG).sequence == sequence

        # An ACK for an outdated seq does not touch the newer row.
        save_product(session, product_id=product.id, name="Café", price="13,00", description="Pacote", ean13="7891234567895")
        stage_configs(session, MASTER, now=2_000)
        mark_published(session, TAG, sequence, version, now=2_010)
        newest = session.exec(select(Publication).order_by(Publication.id.desc())).first()
        assert newest.sequence == sequence + 1 and newest.published_at is None and newest.reason == "produto"


def test_reason_is_inferred_when_worker_stages_without_one(tmp_path):
    engine = make_engine(tmp_path / "catalog.db")
    create_tables(engine)
    with Session(engine) as session:
        product = save_product(session, product_id=None, name="Café", price="12,90", description="Pacote", ean13="7891234567895")
        register_tag(session, TAG)
        stage_configs(session, MASTER)
        link_product(session, TAG, product.id)
        stage_configs(session, MASTER)
        save_product(session, product_id=product.id, name="Café", price="11,90", description="Pacote", ean13="7891234567895")
        stage_configs(session, MASTER)
        reasons = [row.reason for row in session.exec(select(Publication).order_by(Publication.id)).all()]
    assert reasons == ["cadastro", "vinculo", "produto"]


def test_old_database_gains_history_table_and_shows_legacy_message(tmp_path):
    database_path = tmp_path / "existing.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE usuario (id INTEGER PRIMARY KEY, login VARCHAR(80) NOT NULL UNIQUE, senha_hash VARCHAR(100) NOT NULL);
            CREATE TABLE produto (id INTEGER PRIMARY KEY, nome VARCHAR(120) NOT NULL,
                preco_centavos INTEGER NOT NULL, descricao VARCHAR(160) NOT NULL, ean13 VARCHAR(13) NOT NULL UNIQUE,
                promocao_preco_centavos INTEGER, promocao_expira_em INTEGER);
            CREATE TABLE etiqueta (identificador VARCHAR(12) PRIMARY KEY, produto_id INTEGER REFERENCES produto(id),
                versao_desejada VARCHAR(8), sequencia INTEGER NOT NULL DEFAULT 0, mensagem_configuracao VARCHAR);
            INSERT INTO produto (id, nome, preco_centavos, descricao, ean13) VALUES (1, 'Produto existente', 1200, 'Descrição', '7891234567895');
            INSERT INTO etiqueta (identificador, produto_id, versao_desejada, sequencia, mensagem_configuracao)
                VALUES ('A1B2C3D4E5F6', 1, 'abcdef01', 7, '{"dados":"{\\"produto\\":null,\\"promocao\\":null,\\"versao\\":\\"abcdef01\\",\\"seq\\":7}","hmac":"00112233445566778899aabbccddeeff"}');
            """
        )
    app = create_app(Settings(database_path, SESSION_SECRET, False))
    tables = inspect(app.state.engine).get_table_names()
    assert "publicacao" in tables
    columns = {column["name"] for column in inspect(app.state.engine).get_columns("etiqueta")}
    assert {"status_rejeitado_motivo", "status_rejeitado_em", "sequencia_publicada"} <= columns
    with Session(app.state.engine) as session:
        assert session.get(Product, 1).name == "Produto existente"
        assert session.get(Tag, TAG).sequence == 7
    with TestClient(app) as client:
        with Session(app.state.engine) as session:
            create_first_admin(session, "admin", PASSWORD)
        client.post("/login", data={"csrf_token": csrf(client, "/login"), "username": "admin", "password": PASSWORD})
        item = feed(client)
        assert item["has_publication"] is True
        assert item["pub_seq"] == "seq #7" and item["pub_reason"] == "Anterior ao histórico"
        assert item["pub_hmac"] == "0011 2233 4455 6677 8899 aabb ccdd eeff"
        assert item["history"] == []


def test_tag_status_presentation_contact_signal_battery_and_rejection(mqtt_client):
    client, app = mqtt_client
    with Session(app.state.engine) as session:
        register_tag(session, TAG)
    assert feed(client)["contact_state"] == "never"
    now = int(datetime.now(timezone.utc).timestamp())
    status = {"versao": "", "tensao_mv": 3300, "rssi": -72, "firmware": "1.0.0", "instante": 0}
    with Session(app.state.engine) as session:
        record_status(session, f"spt/{TAG}/status", json.dumps(status).encode(), received_at=now - 26 * 3600)
    item = feed(client)
    assert item["contact_state"] == "late" and "25 h" in item["contact_label"]
    assert (item["rssi_state"], item["rssi_label"]) == ("fair", "Sinal regular")
    assert item["battery_state"] == "low" and item["battery"] == "3300 mV"
    assert "%" not in item["battery"] + item["battery_label"]
    assert item["received"].endswith("há 26 h") and "(Brasília)" in item["received"]

    with Session(app.state.engine) as session:
        record_status(session, f"spt/{TAG}/status", json.dumps({**status, "tensao_mv": 3900}).encode(), received_at=now)
    item = feed(client)
    assert item["contact_state"] == "ok" and item["battery_state"] == "ok" and item["rejected_state"] == "none"

    # A rejected status is kept on its own tag, not only in the global banner.
    app.state.mqtt_service._set_status_issue(f"spt/{TAG.lower()}/status", "Campos de estado inválidos (desconhecidos: seq).")
    item = feed(client)
    assert item["rejected_state"] == "recent" and "desconhecidos: seq" in item["rejected"]
    with Session(app.state.engine) as session:
        assert not record_rejected_status(session, "spt/FFFFFFFFFFFF/status", "Etiqueta desconhecida.", now)


def test_presentation_helpers():
    # 2026-10-28 15:00 UTC is 12:00 in Brasília (UTC−3, no daylight saving time).
    instant = int(datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc).timestamp())
    assert local_timestamp(instant) == "28/10/2026 12:00 (Brasília)"
    assert relative_time(instant - 30, instant) == "agora há pouco"
    assert relative_time(instant - 180, instant) == "há 3 min"
    assert relative_time(instant - 3 * 86400, instant) == "há 3 dias"
    assert relative_time(instant + 7200, instant) == "em 2 h"
    assert rssi_quality(-67) == ("good", "Sinal bom")
    assert rssi_quality(-80)[0] == "fair" and rssi_quality(-81)[0] == "weak"
    assert rssi_quality(None)[0] == "unknown" and rssi_quality(0)[0] == "unknown"
    assert battery_status(None, 3500)[0] == "unknown" and battery_status(3499, 3500)[0] == "low"
    assert contact_status(instant - 3600, instant, 180, 60)["contact_state"] == "late"
    assert contact_status(instant - 100, instant, 180, 60)["contact_state"] == "ok"
    assert group_hex("9bb4c082b6209aa642ccf1652b2a5397") == "9bb4 c082 b620 9aa6 42cc f165 2b2a 5397"
    old = '{"produto":{"nome":"Café","preco":990,"descricao":"x","ean13":"7891234567895"},"promocao":null,"versao":"00000000","seq":1}'
    new = '{"produto":{"nome":"Café","preco":850,"descricao":"x","ean13":"7891234567895"},"promocao":null,"versao":"11111111","seq":2}'
    assert describe_changes(old, new) == ["preço R$ 9,90 → R$ 8,50"]
    assert describe_changes(None, new) == ["primeira mensagem registrada"]


def test_monitoring_thresholds_from_environment(monkeypatch):
    monkeypatch.setenv("SPT_SESSION_SECRET", SESSION_SECRET)
    for variable in ("SPT_MQTT_HOST", "SPT_MQTT_USERNAME", "SPT_MQTT_PASSWORD", "SPT_MQTT_MASTER_KEY"):
        monkeypatch.setenv(variable, "")
    monkeypatch.setenv("SPT_TAG_WAKE_INTERVAL_S", "180")
    monkeypatch.setenv("SPT_TAG_WAKE_MARGIN_S", "60")
    monkeypatch.setenv("SPT_BATTERY_LOW_MV", "3600")
    monkeypatch.setattr("smart_price_tag.broker_admin.BrokerManager.ready", lambda self: False)
    settings = Settings.from_env()
    assert (settings.tag_wake_interval_s, settings.tag_wake_margin_s, settings.battery_low_mv) == (180, 60, 3600)
    monkeypatch.setenv("SPT_TAG_WAKE_INTERVAL_S", "0")
    with pytest.raises(RuntimeError):
        Settings.from_env()


def test_timeline_ignores_status_older_than_the_publication(mqtt_client):
    client, app = mqtt_client
    now = int(datetime.now(timezone.utc).timestamp())
    with Session(app.state.engine) as session:
        register_tag(session, TAG)
        status = {"versao": "", "tensao_mv": 3900, "rssi": -60, "firmware": "1.0.0", "instante": 0}
        record_status(session, f"spt/{TAG}/status", json.dumps(status).encode(), received_at=now - 3600)
        stage_configs(session, MASTER, reason="cadastro", now=now - 60)
        tag = session.get(Tag, TAG)
        mark_published(session, TAG, tag.sequence, tag.desired_version, now=now - 50)
    steps = {step["key"]: step for step in feed(client)["timeline"]}
    assert steps["prepared"]["done"] and steps["published"]["done"]
    assert not steps["received"]["done"] and steps["received"]["time"] == "Último status é anterior a esta publicação"
    assert not steps["applied"]["done"]
    with Session(app.state.engine) as session:
        record_status(session, f"spt/{TAG}/status", json.dumps(status).encode(), received_at=now)
    assert {step["key"]: step["done"] for step in feed(client)["timeline"]}["received"] is True
