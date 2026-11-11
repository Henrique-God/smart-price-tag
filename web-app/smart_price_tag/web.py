"""Server-rendered routes for the management application."""

import json
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from . import catalog
from .authentication import authenticate
from .broker_admin import BrokerError, BrokerManager
from .config import Settings
from .db import AdminUser, Product, Publication, Tag, create_tables, make_engine
from .mqtt import MqttService
from .presentation import (
    battery_status,
    contact_status,
    group_hex,
    local_timestamp,
    local_with_relative,
    publication_summary,
    readable_data,
    rssi_quality,
)
from .publisher import REASONS, configuration_version, content_for_tag, recent_publications


ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.filters["price"] = catalog.format_price
templates.env.filters["utc_timestamp"] = catalog.format_utc_timestamp
templates.env.filters["local_time"] = local_timestamp
templates.env.filters["brasilia_input"] = catalog.format_brasilia_input

# Publications listed in each tag's history panel.
HISTORY_LIMIT = 8
# Tags listed with links in the confirmation after a catalog change.
FLASH_TAG_LIMIT = 10


def synchronization_status(session: Session, tag: Tag) -> dict[str, str]:
    """Compare the latest reported content with the catalog, even before MQTT staging."""
    current = configuration_version(content_for_tag(session, tag))
    if tag.last_received_at is None:
        state, label = "unseen", "Etiqueta ainda sem status"
        description = "A etiqueta ainda não enviou nenhum status, então não dá para saber o que ela exibe."
    elif not tag.confirmed_version:
        state, label = "unconfirmed", "Versão não informada"
        description = "O último status chegou sem versão: a etiqueta ainda não aplicou nenhuma configuração ou não informou qual."
    elif tag.confirmed_version == current:
        state, label = "synced", "Etiqueta em dia"
        description = "A versão informada no último status é a mesma do conteúdo atual do catálogo."
    else:
        state, label = "changed", "Etiqueta desatualizada"
        description = "A versão informada no último status difere do conteúdo atual do catálogo. A etiqueta deve atualizar no próximo despertar."
    return {"current": current, "sync_state": state, "sync_label": label, "sync_description": description}


def create_app(settings: Settings | None = None, broker_manager: BrokerManager | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    broker_manager = broker_manager or BrokerManager(ROOT.parent)
    engine = make_engine(settings.database_path)
    create_tables(engine)
    managed_broker = False
    if broker_manager.ready() and settings.mqtt_username == "spt-app":
        try:
            managed_broker = (
                (settings.mqtt_host, settings.mqtt_port) == broker_manager.listener()
                and settings.mqtt_password == broker_manager.app_password_path.read_text(encoding="ascii").strip()
            )
        except (BrokerError, OSError):
            pass
    mqtt_service = MqttService(engine, settings, broker_manager.tag_username if managed_broker else None) if settings.mqtt_host else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if mqtt_service:
            mqtt_service.start()
        try:
            yield
        finally:
            if mqtt_service:
                mqtt_service.stop()

    app = FastAPI(title="Smart Price Tag", lifespan=lifespan)
    app.state.engine = engine
    app.state.mqtt_service = mqtt_service
    app.state.broker_manager = broker_manager
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="spt_session",
        max_age=8 * 60 * 60,
        same_site="strict",
        https_only=settings.secure_cookies,
    )
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

    def render(request: Request, template: str, *, status_code: int = 200, **context):
        token = request.session.setdefault("csrf", secrets.token_urlsafe(32))
        flash_message = request.session.pop("flash_message", None)
        flash_tags = request.session.pop("flash_tags", None)
        return templates.TemplateResponse(
            request=request,
            name=template,
            context={"csrf_token": token, "flash_message": flash_message, "flash_tags": flash_tags, "authenticated": bool(request.session.get("user_id")), **context},
            status_code=status_code,
        )

    def redirect(path: str, message: str | None = None, request: Request | None = None):
        if message and request:
            request.session["flash_message"] = message
        return RedirectResponse(path, status_code=303)

    def tag_sequences(*, product_id: int | None = None, identifier: str | None = None) -> dict[str, int]:
        """Current `seq` of the tags a catalog action can change, read before the action."""
        with Session(engine) as session:
            if identifier is not None:
                tag = session.get(Tag, identifier)
                return {tag.identifier: tag.sequence} if tag else {}
            tags = session.exec(select(Tag).where(Tag.product_id == product_id)).all()
            return {tag.identifier: tag.sequence for tag in tags}

    def catalog_changed(request: Request | None = None, reason: str | None = None, before: dict[str, int] | None = None) -> str:
        """Stage the change with its reason; list the affected tags in the confirmation."""
        if mqtt_service is None:
            return " MQTT não configurado; alteração salva somente no catálogo."
        mqtt_service.notify_change(reason)
        if before is None or request is None:
            return " Configuração preparada para publicação MQTT; veja a situação em Etiquetas."
        if not before:
            return " Nenhuma etiqueta vinculada; nada a publicar."
        items = []
        with Session(engine) as session:
            for identifier, old_sequence in sorted(before.items()):
                tag = session.get(Tag, identifier)
                if tag is not None:
                    items.append({"identifier": tag.identifier, "seq": tag.sequence, "version": tag.desired_version or "—", "new": tag.sequence > old_sequence})
        request.session["flash_tags"] = items[:FLASH_TAG_LIMIT]
        hidden = len(items) - FLASH_TAG_LIMIT
        more = f" (e mais {hidden})" if hidden > 0 else ""
        if any(item["new"] for item in items):
            return f" Nova mensagem assinada para as etiquetas afetadas{more}:"
        return f" O conteúdo das etiquetas afetadas não mudou; a sequência foi mantida{more}:"

    def require_login(request: Request):
        user_id = request.session.get("user_id")
        if not isinstance(user_id, int):
            return redirect("/login")
        with Session(engine) as session:
            if session.get(AdminUser, user_id) is None:
                request.session.clear()
                return redirect("/login")
        return None

    def verify_csrf(request: Request, value: str) -> None:
        expected = request.session.get("csrf")
        if not expected or not secrets.compare_digest(expected, value):
            raise HTTPException(status_code=403, detail="Formulário inválido ou sessão expirada. Recarregue a página.")

    async def read_form(request: Request):
        form = await request.form()
        verify_csrf(request, str(form.get("csrf_token", "")))
        return form

    @app.get("/", include_in_schema=False)
    def home(request: Request):
        return redirect("/produtos" if request.session.get("user_id") else "/login")

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        if request.session.get("user_id"):
            return redirect("/produtos")
        with Session(engine) as session:
            no_admin = session.exec(select(AdminUser.id)).first() is None
        return render(request, "login.html", no_admin=no_admin, error=None, username="")

    @app.post("/login", response_class=HTMLResponse)
    async def login(request: Request):
        form = await read_form(request)
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        with Session(engine) as session:
            user = authenticate(session, username, password)
            no_admin = session.exec(select(AdminUser.id)).first() is None
        if user is None:
            return render(request, "login.html", status_code=400, no_admin=no_admin, error="Login ou senha inválidos.", username=username)
        request.session.clear()
        request.session["user_id"] = user.id
        request.session["csrf"] = secrets.token_urlsafe(32)
        return redirect("/produtos", "Sessão iniciada.", request)

    @app.post("/logout")
    async def logout(request: Request):
        denied = require_login(request)
        if denied:
            return denied
        await read_form(request)
        request.session.clear()
        return redirect("/login")

    @app.get("/produtos", response_class=HTMLResponse)
    def list_products(request: Request):
        denied = require_login(request)
        if denied:
            return denied
        with Session(engine) as session:
            products = session.exec(select(Product).order_by(Product.name, Product.id)).all()
        return render(request, "products.html", products=products, now=int(datetime.now(timezone.utc).timestamp()), mqtt_enabled=mqtt_service is not None)

    def product_form(request: Request, *, title: str, action: str, values: dict, error: str | None = None, status_code: int = 200):
        return render(request, "product_form.html", status_code=status_code, title=title, action=action, values=values, error=error)

    @app.get("/produtos/novo", response_class=HTMLResponse)
    def new_product_form(request: Request):
        denied = require_login(request)
        if denied:
            return denied
        return product_form(request, title="Novo produto", action="/produtos/novo", values={})

    @app.post("/produtos/novo", response_class=HTMLResponse)
    async def create_product(request: Request):
        denied = require_login(request)
        if denied:
            return denied
        form = await read_form(request)
        values = {key: str(form.get(key, "")) for key in ("name", "price", "description", "ean13")}
        try:
            with Session(engine) as session:
                catalog.save_product(session, product_id=None, **values)
        except catalog.CatalogError as error:
            return product_form(request, title="Novo produto", action="/produtos/novo", values=values, error=str(error), status_code=400)
        return redirect("/produtos", "Produto salvo no catálogo." + catalog_changed(request, "produto", {}), request)

    @app.get("/produtos/{product_id}/editar", response_class=HTMLResponse)
    def edit_product_form(request: Request, product_id: int):
        denied = require_login(request)
        if denied:
            return denied
        with Session(engine) as session:
            product = session.get(Product, product_id)
            if product is None:
                raise HTTPException(404, "Produto não encontrado.")
            values = {"name": product.name, "price": catalog.format_price(product.price_cents), "description": product.description, "ean13": product.ean13}
        return product_form(request, title="Editar produto", action=f"/produtos/{product_id}/editar", values=values)

    @app.post("/produtos/{product_id}/editar", response_class=HTMLResponse)
    async def edit_product(request: Request, product_id: int):
        denied = require_login(request)
        if denied:
            return denied
        form = await read_form(request)
        values = {key: str(form.get(key, "")) for key in ("name", "price", "description", "ean13")}
        before = tag_sequences(product_id=product_id)
        try:
            with Session(engine) as session:
                catalog.save_product(session, product_id=product_id, **values)
        except catalog.CatalogError as error:
            return product_form(request, title="Editar produto", action=f"/produtos/{product_id}/editar", values=values, error=str(error), status_code=400)
        return redirect("/produtos", "Produto atualizado no catálogo." + catalog_changed(request, "produto", before), request)

    @app.post("/produtos/{product_id}/excluir")
    async def delete_product(request: Request, product_id: int):
        denied = require_login(request)
        if denied:
            return denied
        await read_form(request)
        try:
            with Session(engine) as session:
                catalog.delete_product(session, product_id)
        except catalog.CatalogError as error:
            return redirect("/produtos", str(error), request)
        return redirect("/produtos", "Produto excluído do catálogo.", request)

    @app.get("/produtos/{product_id}/promocao", response_class=HTMLResponse)
    def promotion_form(request: Request, product_id: int):
        denied = require_login(request)
        if denied:
            return denied
        with Session(engine) as session:
            product = session.get(Product, product_id)
            if product is None:
                raise HTTPException(404, "Produto não encontrado.")
            values = {
                "price": catalog.format_price(product.promotion_price_cents) if product.promotion_price_cents else "",
                "ends_at": catalog.format_brasilia_input(product.promotion_ends_at) if product.promotion_ends_at else "",
            }
        return render(request, "promotion_form.html", product=product, values=values, error=None)

    @app.post("/produtos/{product_id}/promocao", response_class=HTMLResponse)
    async def save_promotion(request: Request, product_id: int):
        denied = require_login(request)
        if denied:
            return denied
        form = await read_form(request)
        values = {"price": str(form.get("price", "")), "ends_at": str(form.get("ends_at", ""))}
        before = tag_sequences(product_id=product_id)
        with Session(engine) as session:
            product = session.get(Product, product_id)
            if product is None:
                raise HTTPException(404, "Produto não encontrado.")
            try:
                catalog.save_promotion(session, product_id, **values)
            except catalog.CatalogError as error:
                return render(request, "promotion_form.html", status_code=400, product=product, values=values, error=str(error))
        return redirect("/produtos", "Promoção salva no catálogo." + catalog_changed(request, "promocao", before), request)

    @app.post("/produtos/{product_id}/promocao/remover")
    async def remove_promotion(request: Request, product_id: int):
        denied = require_login(request)
        if denied:
            return denied
        await read_form(request)
        before = tag_sequences(product_id=product_id)
        try:
            with Session(engine) as session:
                catalog.remove_promotion(session, product_id)
        except catalog.CatalogError as error:
            return redirect("/produtos", str(error), request)
        return redirect("/produtos", "Promoção removida do catálogo." + catalog_changed(request, "promocao", before), request)

    def delivery_state(tag: Tag) -> tuple[str, str]:
        """Stage of the latest message: Preparada → Publicada → Status recebido → Aplicada."""
        if mqtt_service is None:
            return "pending", "MQTT não configurado"
        if not tag.desired_version or not tag.pending_payload:
            return "pending", "Preparando mensagem"
        if tag.published_sequence != tag.sequence or tag.published_version != tag.desired_version:
            return "pending", "Aguardando envio ao broker"
        if tag.confirmed_version == tag.desired_version and tag.confirmed_sequence == tag.sequence:
            return "applied", "Aplicada pela etiqueta"
        if tag.last_received_at is not None:
            return "received", "Status recebido · versão ainda não confirmada"
        return "waiting", "No broker · aguardando status da etiqueta"

    def expected_topic(identifier: str) -> str:
        topic_id = None
        if mqtt_service is not None and mqtt_service.topic_identifier is not None:
            try:
                topic_id = mqtt_service.topic_identifier(identifier)
            except (BrokerError, catalog.CatalogError):
                topic_id = None
        return f"spt/{topic_id or identifier}/config"

    def last_message(tag: Tag, publication: Publication | None) -> Publication | None:
        """Latest signed message; databases older than the history fall back to the pending payload."""
        if publication is not None and publication.sequence == tag.sequence:
            return publication
        if not tag.pending_payload:
            return publication
        try:
            envelope = json.loads(tag.pending_payload)
        except json.JSONDecodeError:
            return publication
        return Publication(identifier=tag.identifier, sequence=tag.sequence, version=tag.desired_version or "",
                           data=envelope.get("dados", ""), hmac=envelope.get("hmac", ""), reason="anterior",
                           prepared_at=0, product_id=tag.product_id)

    def delivery_timeline(tag: Tag, message: Publication | None, state: str, now: int) -> list[dict]:
        published = state in {"waiting", "received", "applied"}
        applied = state == "applied"
        published_at = message.published_at if message else None
        # delivery_state counts any status; here only one sent after this message's ACK counts.
        stale_status = published_at is not None and tag.last_received_at is not None and tag.last_received_at < published_at
        received = applied or (state == "received" and not stale_status)
        if received:
            received_time = local_with_relative(tag.last_received_at, now)
        elif stale_status:
            received_time = "Último status é anterior a esta publicação"
        else:
            received_time = "Aguardando o próximo status da etiqueta"
        return [
            {"key": "prepared", "label": "Preparada", "done": message is not None,
             "time": local_with_relative(message.prepared_at, now) if message and message.prepared_at else ("Antes do histórico" if message else "Nenhuma mensagem preparada")},
            {"key": "published", "label": "Publicada no broker (ACK)", "done": published,
             "time": local_with_relative(published_at, now) if published and published_at else ("Confirmada" if published else "Aguardando ACK do broker")},
            {"key": "received", "label": "Status recebido", "done": received, "time": received_time},
            {"key": "applied", "label": "Aplicada pela etiqueta", "done": applied,
             "time": "A etiqueta informou esta versão" if applied
             else f"Aguardando status com versao {message.version}" if message and message.version else "Aguardando a etiqueta"},
        ]

    def tag_view(session: Session, tag: Tag, now: int, *, history: bool = True) -> dict:
        """Everything a tag panel shows; strings so tag_status.js can update the page."""
        state, label = delivery_state(tag)
        publications = recent_publications(session, tag.identifier, HISTORY_LIMIT + 1)
        message = last_message(tag, publications[0] if publications else None)
        rssi_state, rssi_label = rssi_quality(tag.rssi)
        battery_state, battery_label = battery_status(tag.battery_mv, settings.battery_low_mv)
        rejected_recent = tag.rejected_status_at is not None and (tag.last_received_at is None or tag.rejected_status_at >= tag.last_received_at)
        view = {
            **synchronization_status(session, tag),
            **contact_status(tag.last_received_at, now, settings.tag_wake_interval_s, settings.tag_wake_margin_s),
            "identifier": tag.identifier,
            "state": state,
            "label": label,
            "desired": tag.desired_version or "—",
            "published": tag.published_version or "—",
            "confirmed": tag.confirmed_version or "Não informada",
            "received": local_with_relative(tag.last_received_at, now, "Nenhum estado recebido"),
            "battery": f"{tag.battery_mv} mV" if tag.battery_mv is not None else "Sem leitura",
            "battery_state": battery_state,
            "battery_label": battery_label,
            "rssi": f"{tag.rssi} dBm" if tag.rssi is not None else "Sem leitura",
            "rssi_state": rssi_state,
            "rssi_label": rssi_label,
            "firmware": tag.firmware or "Sem leitura",
            "sequence": str(tag.sequence),
            "published_sequence": str(tag.published_sequence),
            "rejected_state": "none" if tag.rejected_status_at is None else ("recent" if rejected_recent else "old"),
            "rejected": "Nenhum status rejeitado" if tag.rejected_status_at is None else (tag.rejected_status_reason or "Motivo não registrado"),
            "rejected_at": local_with_relative(tag.rejected_status_at, now, ""),
            "has_publication": message is not None,
        }
        if message is not None:
            published_at = message.published_at if tag.published_sequence == message.sequence else None
            view.update({
                "pub_seq": f"seq #{message.sequence}",
                "pub_version": message.version or "—",
                "pub_hmac": group_hex(message.hmac),
                "pub_topic": message.topic or expected_topic(tag.identifier),
                "pub_reason": REASONS.get(message.reason, "Anterior ao histórico"),
                "pub_prepared": local_with_relative(message.prepared_at or None, now, "Antes do histórico"),
                "pub_published": local_with_relative(published_at, now, "Confirmada pelo broker" if tag.published_sequence == message.sequence else "Aguardando ACK do broker"),
                "pub_republished": local_with_relative(message.republished_at, now, "Nenhum reenvio"),
                "pub_data": message.data,
                **readable_data(message.data, now),
            })
        else:
            view.update({key: "—" for key in ("pub_seq", "pub_version", "pub_hmac", "pub_topic", "pub_reason", "pub_prepared",
                                               "pub_published", "pub_republished", "pub_data", "pub_name", "pub_price",
                                               "pub_description", "pub_ean13", "pub_promotion")})
        view["timeline"] = delivery_timeline(tag, message, state, now)
        if history:
            shown = publications[:HISTORY_LIMIT]
            view["history"] = [
                publication_summary(item, publications[index + 1].data if index + 1 < len(publications) else None, now, superseded=index > 0)
                for index, item in enumerate(shown)
            ]
        return view

    def mqtt_page(request: Request, *, error: str | None = None, credentials: dict | None = None, status_code: int = 200):
        with Session(engine) as session:
            tags = session.exec(select(Tag).order_by(Tag.identifier)).all()
        try:
            accounts = broker_manager.provisioned_accounts()
        except BrokerError as exc:
            accounts = {}
            error = error or str(exc)
        try:
            listener_host, listener_port = broker_manager.listener() if broker_manager.ready() else ("127.0.0.1", 1884)
        except BrokerError as exc:
            listener_host, listener_port = "127.0.0.1", 1884
            error = error or str(exc)

        counts = {"pending": 0, "waiting": 0, "received": 0, "applied": 0}
        rows = []
        now = int(time.time())
        with Session(engine) as session:
            for tag in tags:
                view = tag_view(session, tag, now, history=False)
                counts[view["state"]] += 1
                rows.append({"tag": tag, "view": view, "state": view["state"], "label": view["label"], "mqtt_username": accounts.get(tag.identifier), "provisioned": tag.identifier in accounts})

        response = render(
            request,
            "mqtt.html",
            status_code=status_code,
            mqtt_enabled=mqtt_service is not None,
            broker_connected=bool(mqtt_service and mqtt_service.connected.is_set()),
            broker_host=settings.mqtt_host,
            broker_port=settings.mqtt_port,
            broker_username=settings.mqtt_username,
            broker_ready=broker_manager.ready(),
            last_status_issue=mqtt_service.last_status_issue() if mqtt_service else None,
            listener_host=listener_host,
            listener_port=listener_port,
            local_ipv4_addresses=broker_manager.local_ipv4_addresses(),
            error=error,
            credentials=credentials,
            rows=rows,
            counts=counts,
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/mqtt", response_class=HTMLResponse)
    def mqtt_dashboard(request: Request):
        denied = require_login(request)
        if denied:
            return denied
        return mqtt_page(request)

    @app.get("/mqtt/estado")
    def mqtt_status_feed(request: Request):
        denied = require_login(request)
        if denied:
            return denied
        now = int(time.time())
        with Session(engine) as session:
            tags = session.exec(select(Tag).order_by(Tag.identifier)).all()
            items = []
            counts = {"pending": 0, "waiting": 0, "received": 0, "applied": 0}
            for tag in tags:
                view = tag_view(session, tag, now)
                counts[view["state"]] += 1
                items.append(view)
        return JSONResponse({"tags": items, "counts": counts}, headers={"Cache-Control": "no-store"})

    @app.post("/mqtt/preparar")
    async def prepare_broker(request: Request):
        denied = require_login(request)
        if denied:
            return denied
        await read_form(request)
        try:
            broker_manager.bootstrap()
        except BrokerError as error:
            return mqtt_page(request, error=str(error), status_code=400)
        return redirect("/mqtt", "Arquivos do broker preparados. Reinicie o backend para usar a configuração local.", request)

    @app.post("/mqtt/listener")
    async def save_broker_listener(request: Request):
        denied = require_login(request)
        if denied:
            return denied
        form = await read_form(request)
        try:
            broker_manager.save_listener(str(form.get("host", "")), str(form.get("port", "")))
        except BrokerError as error:
            return mqtt_page(request, error=str(error), status_code=400)
        return redirect("/mqtt", "Endereço salvo. Reinicie o broker e o backend para aplicar a mudança.", request)

    @app.post("/mqtt/etiquetas")
    async def provision_mqtt_tag(request: Request):
        denied = require_login(request)
        if denied:
            return denied
        form = await read_form(request)
        if not broker_manager.ready():
            return mqtt_page(request, error="Prepare os arquivos do broker antes de provisionar etiquetas.", status_code=400)
        try:
            identifier = catalog.validate_identifier(str(form.get("identifier", "")))
            with Session(engine) as session:
                if session.get(Tag, identifier) is None:
                    catalog.register_tag(session, identifier)
            password, key = broker_manager.provision_tag(identifier, username_case=str(form.get("username_case", "upper")))
        except (catalog.CatalogError, BrokerError) as error:
            return mqtt_page(request, error=str(error), status_code=400)
        return mqtt_page(request, credentials={"identifier": identifier, "username": broker_manager.tag_username(identifier), "password": password, "key": key})

    @app.post("/mqtt/etiquetas/{identifier}/rotacionar")
    async def rotate_mqtt_tag(request: Request, identifier: str):
        denied = require_login(request)
        if denied:
            return denied
        await read_form(request)
        try:
            identifier = catalog.validate_identifier(identifier)
            with Session(engine) as session:
                catalog.get_tag(session, identifier)
            password, key = broker_manager.provision_tag(identifier, rotate=True)
        except (catalog.CatalogError, BrokerError) as error:
            return mqtt_page(request, error=str(error), status_code=400)
        return mqtt_page(request, credentials={"identifier": identifier, "username": broker_manager.tag_username(identifier), "password": password, "key": key})

    @app.post("/mqtt/etiquetas/{identifier}/usuario")
    async def change_mqtt_tag_username(request: Request, identifier: str):
        denied = require_login(request)
        if denied:
            return denied
        form = await read_form(request)
        try:
            username = broker_manager.set_tag_username_case(identifier, str(form.get("username_case", "")))
        except (catalog.CatalogError, BrokerError) as error:
            return mqtt_page(request, error=str(error), status_code=400)
        if mqtt_service is not None and managed_broker:
            mqtt_service.request_republish()
        return redirect("/mqtt", f"Usuário e tópicos MQTT alterados para {username}. A senha foi mantida. Reinicie o broker para aplicar.", request)

    @app.post("/mqtt/etiquetas/{identifier}/revogar")
    async def revoke_mqtt_tag(request: Request, identifier: str):
        denied = require_login(request)
        if denied:
            return denied
        await read_form(request)
        try:
            broker_manager.revoke_tag(identifier)
        except (catalog.CatalogError, BrokerError) as error:
            return mqtt_page(request, error=str(error), status_code=400)
        return redirect("/mqtt", "Acesso MQTT removido dos arquivos. Reinicie o broker para aplicar a revogação.", request)

    @app.post("/mqtt/republicar")
    async def republish_mqtt(request: Request):
        denied = require_login(request)
        if denied:
            return denied
        await read_form(request)
        if mqtt_service is None:
            return redirect("/mqtt", "Configure o MQTT no servidor antes de republicar.", request)
        mqtt_service.request_republish()
        message = (
            "Republicação solicitada. Atualize a página para acompanhar as etiquetas."
            if mqtt_service.connected.is_set()
            else "Broker desconectado. As configurações serão reenviadas após a reconexão."
        )
        return redirect("/mqtt", message, request)

    def tag_page(request: Request, *, error: str | None = None, identifier: str = "", status_code: int = 200):
        with Session(engine) as session:
            tags = session.exec(select(Tag).order_by(Tag.identifier)).all()
            products = session.exec(select(Product).order_by(Product.name, Product.id)).all()
            product_names = {product.id: product.name for product in products}
            now = int(time.time())
            tag_rows = [{"tag": tag, **tag_view(session, tag, now)} for tag in tags]
        return render(request, "tags.html", status_code=status_code, tag_rows=tag_rows, products=products, product_names=product_names, error=error, identifier=identifier, mqtt_enabled=mqtt_service is not None, broker_connected=bool(mqtt_service and mqtt_service.connected.is_set()))

    @app.get("/etiquetas", response_class=HTMLResponse)
    def list_tags(request: Request):
        denied = require_login(request)
        if denied:
            return denied
        return tag_page(request)

    @app.post("/etiquetas", response_class=HTMLResponse)
    async def create_tag(request: Request):
        denied = require_login(request)
        if denied:
            return denied
        form = await read_form(request)
        identifier = str(form.get("identifier", ""))
        try:
            with Session(engine) as session:
                registered = catalog.register_tag(session, identifier).identifier
        except catalog.CatalogError as error:
            return tag_page(request, error=str(error), identifier=identifier, status_code=400)
        return redirect("/etiquetas", "Etiqueta cadastrada no catálogo. Provisione o acesso dela na tela MQTT." + catalog_changed(request, "cadastro", {registered: 0}), request)

    @app.post("/etiquetas/{identifier}/vinculo")
    async def change_link(request: Request, identifier: str):
        denied = require_login(request)
        if denied:
            return denied
        form = await read_form(request)
        value = str(form.get("product_id", ""))
        if value and (not value.isascii() or not value.isdecimal() or len(value) > 18 or int(value) <= 0):
            return redirect("/etiquetas", "Selecione um produto válido.", request)
        before = tag_sequences(identifier=identifier)
        try:
            with Session(engine) as session:
                catalog.link_product(session, identifier, int(value) if value else None)
        except catalog.CatalogError as error:
            return redirect("/etiquetas", str(error), request)
        return redirect("/etiquetas", "Vínculo salvo no catálogo." + catalog_changed(request, "vinculo", before), request)

    return app
