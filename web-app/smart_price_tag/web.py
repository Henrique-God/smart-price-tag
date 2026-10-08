"""Server-rendered routes for the management application."""

import secrets
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
from .db import AdminUser, Product, Tag, create_tables, make_engine
from .mqtt import MqttService
from .publisher import configuration_version, content_for_tag


ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.filters["price"] = catalog.format_price
templates.env.filters["utc_timestamp"] = catalog.format_utc_timestamp
templates.env.filters["utc_input"] = catalog.format_utc_input


def synchronization_status(session: Session, tag: Tag) -> dict[str, str]:
    """Compare the latest reported content with the catalog, even before MQTT staging."""
    current = configuration_version(content_for_tag(session, tag))
    if tag.last_received_at is None:
        state, label = "unseen", "Aguardando status da etiqueta"
        description = "A etiqueta ainda não enviou um status para comparar com a configuração atual."
    elif not tag.confirmed_version:
        state, label = "unconfirmed", "Sincronização não confirmada"
        description = "Recebemos um status, mas a etiqueta não informou a versão da configuração."
    elif tag.confirmed_version == current:
        state, label = "synced", "Etiqueta sincronizada"
        description = "A versão do último status recebido corresponde à configuração atual do catálogo."
    else:
        state, label = "changed", "Etiqueta não sincronizada"
        description = "A versão do último status recebido difere da configuração atual. Aguardando atualização da etiqueta."
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
        return templates.TemplateResponse(
            request=request,
            name=template,
            context={"csrf_token": token, "flash_message": flash_message, "authenticated": bool(request.session.get("user_id")), **context},
            status_code=status_code,
        )

    def redirect(path: str, message: str | None = None, request: Request | None = None):
        if message and request:
            request.session["flash_message"] = message
        return RedirectResponse(path, status_code=303)

    def catalog_changed() -> str:
        if mqtt_service is None:
            return " MQTT não configurado; alteração salva somente no catálogo."
        mqtt_service.notify_change()
        return " Configuração preparada para publicação MQTT; veja a situação em Etiquetas."

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
        return redirect("/produtos", "Produto salvo no catálogo." + catalog_changed(), request)

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
        try:
            with Session(engine) as session:
                catalog.save_product(session, product_id=product_id, **values)
        except catalog.CatalogError as error:
            return product_form(request, title="Editar produto", action=f"/produtos/{product_id}/editar", values=values, error=str(error), status_code=400)
        return redirect("/produtos", "Produto atualizado no catálogo." + catalog_changed(), request)

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
                "ends_at": catalog.format_utc_input(product.promotion_ends_at) if product.promotion_ends_at else "",
            }
        return render(request, "promotion_form.html", product=product, values=values, error=None)

    @app.post("/produtos/{product_id}/promocao", response_class=HTMLResponse)
    async def save_promotion(request: Request, product_id: int):
        denied = require_login(request)
        if denied:
            return denied
        form = await read_form(request)
        values = {"price": str(form.get("price", "")), "ends_at": str(form.get("ends_at", ""))}
        with Session(engine) as session:
            product = session.get(Product, product_id)
            if product is None:
                raise HTTPException(404, "Produto não encontrado.")
            try:
                catalog.save_promotion(session, product_id, **values)
            except catalog.CatalogError as error:
                return render(request, "promotion_form.html", status_code=400, product=product, values=values, error=str(error))
        return redirect("/produtos", "Promoção salva no catálogo." + catalog_changed(), request)

    @app.post("/produtos/{product_id}/promocao/remover")
    async def remove_promotion(request: Request, product_id: int):
        denied = require_login(request)
        if denied:
            return denied
        await read_form(request)
        try:
            with Session(engine) as session:
                catalog.remove_promotion(session, product_id)
        except catalog.CatalogError as error:
            return redirect("/produtos", str(error), request)
        return redirect("/produtos", "Promoção removida do catálogo." + catalog_changed(), request)

    def delivery_state(tag: Tag) -> tuple[str, str]:
        if mqtt_service is None:
            return "pending", "MQTT não configurado"
        if not tag.desired_version or not tag.pending_payload:
            return "pending", "Preparando publicação"
        if tag.published_sequence != tag.sequence or tag.published_version != tag.desired_version:
            return "pending", "Publicação pendente"
        if tag.confirmed_version == tag.desired_version and tag.confirmed_sequence == tag.sequence:
            return "applied", "Aplicada"
        if tag.last_received_at is not None:
            return "received", "Estado recebido · aguardando confirmação"
        return "waiting", "Aguardando primeiro estado"

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
        for tag in tags:
            state, label = delivery_state(tag)
            counts[state] += 1
            rows.append({"tag": tag, "state": state, "label": label, "mqtt_username": accounts.get(tag.identifier), "provisioned": tag.identifier in accounts})

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
        with Session(engine) as session:
            tags = session.exec(select(Tag).order_by(Tag.identifier)).all()
            items = []
            counts = {"pending": 0, "waiting": 0, "received": 0, "applied": 0}
            for tag in tags:
                state, label = delivery_state(tag)
                counts[state] += 1
                items.append({
                    **synchronization_status(session, tag),
                    "identifier": tag.identifier,
                    "state": state,
                    "label": label,
                    "desired": tag.desired_version or "—",
                    "published": tag.published_version or "—",
                    "confirmed": tag.confirmed_version or "Não informada",
                    "received": catalog.format_utc_timestamp(tag.last_received_at) if tag.last_received_at else "Nenhum estado recebido",
                    "battery": f"{tag.battery_mv} mV" if tag.battery_mv is not None else "Sem leitura",
                    "rssi": f"{tag.rssi} dBm" if tag.rssi is not None else "Sem leitura",
                    "firmware": tag.firmware or "Sem leitura",
                })
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
            tag_rows = []
            for tag in tags:
                state, label = delivery_state(tag)
                tag_rows.append({"tag": tag, "state": state, "label": label, **synchronization_status(session, tag)})
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
                catalog.register_tag(session, identifier)
        except catalog.CatalogError as error:
            return tag_page(request, error=str(error), identifier=identifier, status_code=400)
        return redirect("/etiquetas", "Etiqueta cadastrada no catálogo. Provisione o acesso dela na tela MQTT." + catalog_changed(), request)

    @app.post("/etiquetas/{identifier}/vinculo")
    async def change_link(request: Request, identifier: str):
        denied = require_login(request)
        if denied:
            return denied
        form = await read_form(request)
        value = str(form.get("product_id", ""))
        if value and (not value.isascii() or not value.isdecimal() or len(value) > 18 or int(value) <= 0):
            return redirect("/etiquetas", "Selecione um produto válido.", request)
        try:
            with Session(engine) as session:
                catalog.link_product(session, identifier, int(value) if value else None)
        except catalog.CatalogError as error:
            return redirect("/etiquetas", str(error), request)
        return redirect("/etiquetas", "Vínculo salvo no catálogo." + catalog_changed(), request)

    return app
