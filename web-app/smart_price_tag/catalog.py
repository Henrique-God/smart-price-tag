"""Catalog rules and server-side validation, independent of the web layer."""

import re
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .db import Product, Tag


class CatalogError(ValueError):
    pass


def parse_price_cents(value: str) -> int:
    value = value.strip()
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,7})[,.][0-9]{2}", value):
        raise CatalogError("Informe o preço com duas casas decimais, por exemplo 12,90.")
    whole, cents = re.split(r"[,.]", value)
    result = int(whole) * 100 + int(cents)
    if result <= 0:
        raise CatalogError("O preço deve ser maior que zero.")
    return result


def format_price(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d}"


def validate_ean13(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[0-9]{13}", value):
        raise CatalogError("O EAN-13 deve conter exatamente 13 dígitos.")
    digits = [int(digit) for digit in value]
    weighted_sum = sum(digit if index % 2 == 0 else 3 * digit for index, digit in enumerate(digits[:12]))
    if (10 - weighted_sum % 10) % 10 != digits[12]:
        raise CatalogError("O dígito verificador do EAN-13 é inválido.")
    return value


def validate_identifier(value: str) -> str:
    identifier = re.sub(r"[:-]", "", value.strip()).upper()
    if not re.fullmatch(r"[0-9A-F]{12}", identifier):
        raise CatalogError("Use o MAC da etiqueta: 12 dígitos hexadecimais, com ou sem separadores.")
    return identifier


def get_product(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise CatalogError("Produto não encontrado.")
    return product


def get_tag(session: Session, identifier: str) -> Tag:
    tag = session.get(Tag, identifier)
    if tag is None:
        raise CatalogError("Etiqueta não encontrada.")
    return tag


def save_product(session: Session, *, product_id: int | None, name: str, price: str, description: str, ean13: str) -> Product:
    name = name.strip()
    description = description.strip()
    if not 1 <= len(name) <= 120:
        raise CatalogError("O nome deve ter de 1 a 120 caracteres.")
    if not 1 <= len(description) <= 160:
        raise CatalogError("A descrição curta deve ter de 1 a 160 caracteres.")
    price_cents = parse_price_cents(price)
    barcode = validate_ean13(ean13)
    existing = session.exec(select(Product).where(Product.ean13 == barcode)).first()
    if existing is not None and existing.id != product_id:
        raise CatalogError("Já existe um produto com este EAN-13.")
    product = get_product(session, product_id) if product_id is not None else Product(name="", price_cents=1, description="", ean13=barcode)
    if product.promotion_price_cents is not None and product.promotion_price_cents >= price_cents:
        raise CatalogError("O preço normal deve continuar maior que o preço promocional. Ajuste a promoção antes.")
    product.name = name
    product.price_cents = price_cents
    product.description = description
    product.ean13 = barcode
    session.add(product)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise CatalogError("Já existe um produto com este EAN-13.") from error
    session.refresh(product)
    return product


def delete_product(session: Session, product_id: int) -> None:
    product = get_product(session, product_id)
    if session.exec(select(Tag.identifier).where(Tag.product_id == product_id)).first() is not None:
        raise CatalogError("Desvincule o produto de todas as etiquetas antes de excluí-lo.")
    session.delete(product)
    session.commit()


def register_tag(session: Session, identifier: str) -> Tag:
    identifier = validate_identifier(identifier)
    if session.get(Tag, identifier):
        raise CatalogError("Já existe uma etiqueta com este identificador.")
    tag = Tag(identifier=identifier)
    session.add(tag)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise CatalogError("Já existe uma etiqueta com este identificador.") from error
    return tag


def link_product(session: Session, identifier: str, product_id: int | None) -> None:
    tag = get_tag(session, identifier)
    if product_id is not None:
        get_product(session, product_id)
    tag.product_id = product_id
    session.add(tag)
    session.commit()


def save_promotion(session: Session, product_id: int, price: str, ends_at: str, *, now: datetime | None = None) -> None:
    product = get_product(session, product_id)
    cents = parse_price_cents(price)
    if cents >= product.price_cents:
        raise CatalogError("O preço promocional deve ser menor que o preço normal.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", ends_at):
        raise CatalogError("Informe data e hora de término em UTC.")
    try:
        end_time = datetime.strptime(ends_at, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise CatalogError("A data de término é inválida.") from error
    now = now or datetime.now(timezone.utc)
    if end_time <= now:
        raise CatalogError("O término da promoção deve estar no futuro (UTC).")
    product.promotion_price_cents = cents
    product.promotion_ends_at = int(end_time.timestamp())
    session.add(product)
    session.commit()


def remove_promotion(session: Session, product_id: int) -> None:
    product = get_product(session, product_id)
    if product.promotion_price_cents is None:
        raise CatalogError("Este produto não possui promoção.")
    product.promotion_price_cents = None
    product.promotion_ends_at = None
    session.add(product)
    session.commit()


def format_utc_timestamp(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


def format_utc_input(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M")
