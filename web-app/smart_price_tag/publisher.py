"""Build durable per-tag desired configurations from committed catalog content."""

import hashlib
import json

from sqlmodel import Session, select

from .db import Product, Tag
from .security import sign_data


def serialize(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def content_for_tag(session: Session, tag: Tag) -> dict:
    product = session.get(Product, tag.product_id) if tag.product_id is not None else None
    if product is None:
        return {"produto": None, "promocao": None}
    promotion = None
    if product.promotion_price_cents is not None and product.promotion_ends_at is not None:
        promotion = {"preco": product.promotion_price_cents, "expira_em": product.promotion_ends_at}
    return {
        "produto": {"nome": product.name, "preco": product.price_cents, "descricao": product.description, "ean13": product.ean13},
        "promocao": promotion,
    }


def stage_configs(session: Session, master_key: bytes) -> int:
    """Reconcile all tags, including changes committed just before a process crash."""
    changed = 0
    for tag in session.exec(select(Tag).order_by(Tag.identifier)).all():
        content = content_for_tag(session, tag)
        version = hashlib.sha256(serialize(content).encode("utf-8")).hexdigest()[:8]
        if tag.desired_version == version and tag.pending_payload:
            continue
        tag.sequence += 1
        data = serialize({**content, "versao": version, "seq": tag.sequence})
        tag.pending_payload = serialize({"dados": data, "hmac": sign_data(master_key, tag.identifier, data)})
        tag.desired_version = version
        session.add(tag)
        changed += 1
    if changed:
        session.commit()
    return changed


def mark_published(session: Session, identifier: str, sequence: int, version: str) -> None:
    tag = session.get(Tag, identifier)
    if tag is not None and tag.sequence == sequence and tag.desired_version == version:
        tag.published_sequence = sequence
        tag.published_version = version
        session.add(tag)
        session.commit()
