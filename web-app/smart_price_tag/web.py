"""Server-rendered routes for the management application."""

import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from . import catalog
from .authentication import authenticate
from .config import Settings
from .db import AdminUser, Product, Tag, create_tables, make_engine
from .mqtt import MqttService


ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.filters["price"] = catalog.format_price
templates.env.filters["utc_timestamp"] = catalog.format_utc_timestamp
templates.env.filters["utc_input"] = catalog.format_utc_input


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_path)
    create_tables(engine)
    mqtt_service = MqttService(engine, settings) if settings.mqtt_host else None

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

    def tag_page(request: Request, *, error: str | None = None, identifier: str = "", status_code: int = 200):
        with Session(engine) as session:
            tags = session.exec(select(Tag).order_by(Tag.identifier)).all()
            products = session.exec(select(Product).order_by(Product.name, Product.id)).all()
            product_names = {product.id: product.name for product in products}
        return render(request, "tags.html", status_code=status_code, tags=tags, products=products, product_names=product_names, error=error, identifier=identifier, mqtt_enabled=mqtt_service is not None, broker_connected=bool(mqtt_service and mqtt_service.connected.is_set()))

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
        return redirect("/etiquetas", "Etiqueta cadastrada no catálogo." + catalog_changed(), request)

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
