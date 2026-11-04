"""Build durable per-tag desired configurations from committed catalog content."""

import hashlib
import json
import time

from sqlmodel import Session, select

from .db import Product, Publication, Tag
from .security import sign_data


# Why a new `seq` was signed. Republishing never creates a row (see mark_published).
REASONS = {
    "produto": "Produto editado",
    "promocao": "Promoção",
    "vinculo": "Vínculo",
    "cadastro": "Etiqueta cadastrada",
    "sincronizacao": "Sincronização",
}


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


def configuration_version(content: dict) -> str:
    return hashlib.sha256(serialize(content).encode("utf-8")).hexdigest()[:8]


def latest_publication(session: Session, identifier: str) -> Publication | None:
    return session.exec(select(Publication).where(Publication.identifier == identifier).order_by(Publication.id.desc())).first()


def publication_for(session: Session, identifier: str, sequence: int) -> Publication | None:
    statement = select(Publication).where(Publication.identifier == identifier, Publication.sequence == sequence)
    return session.exec(statement.order_by(Publication.id.desc())).first()


def recent_publications(session: Session, identifier: str, limit: int = 10) -> list[Publication]:
    statement = select(Publication).where(Publication.identifier == identifier).order_by(Publication.id.desc()).limit(limit)
    return list(session.exec(statement).all())


def infer_reason(previous: Publication | None, content: dict, product_id: int | None) -> str:
    """Reason for a change staged without one, e.g. by the worker's reconciliation."""
    if previous is None:
        return "vinculo" if product_id is not None else "cadastro"
    if previous.product_id != product_id:
        return "vinculo"
    try:
        old = json.loads(previous.data)
    except json.JSONDecodeError:
        return "sincronizacao"
    if old.get("produto") != content["produto"]:
        return "produto"
    if old.get("promocao") != content["promocao"]:
        return "promocao"
    return "sincronizacao"


def stage_configs(session: Session, master_key: bytes, *, reason: str | None = None, now: int | None = None) -> int:
    """Reconcile all tags, including changes committed just before a process crash.

    Each new `seq` is also recorded in `publicacao`. `reason` comes from the
    catalog action that caused the change; without it, it is inferred by
    comparing with the previous publication.
    """
    if reason is not None and reason not in REASONS:
        raise ValueError(f"Motivo de publicação desconhecido: {reason}")
    changed = 0
    now = int(time.time()) if now is None else now
    for tag in session.exec(select(Tag).order_by(Tag.identifier)).all():
        content = content_for_tag(session, tag)
        version = configuration_version(content)
        if tag.desired_version == version and tag.pending_payload:
            continue
        tag.sequence += 1
        data = serialize({**content, "versao": version, "seq": tag.sequence})
        signature = sign_data(master_key, tag.identifier, data)
        tag.pending_payload = serialize({"dados": data, "hmac": signature})
        tag.desired_version = version
        session.add(tag)
        session.add(Publication(
            identifier=tag.identifier,
            sequence=tag.sequence,
            version=version,
            data=data,
            hmac=signature,
            product_id=tag.product_id,
            reason=reason or infer_reason(latest_publication(session, tag.identifier), content, tag.product_id),
            prepared_at=now,
        ))
        changed += 1
    if changed:
        session.commit()
    return changed


def mark_published(session: Session, identifier: str, sequence: int, version: str, *, topic: str | None = None, now: int | None = None) -> None:
    """Record the broker ACK. A resend of the same `seq` only updates `republicada_em`."""
    tag = session.get(Tag, identifier)
    if tag is None or tag.sequence != sequence or tag.desired_version != version:
        return
    tag.published_sequence = sequence
    tag.published_version = version
    session.add(tag)
    publication = publication_for(session, identifier, sequence)
    if publication is not None:
        now = int(time.time()) if now is None else now
        if publication.published_at is None:
            publication.published_at = now
        else:
            publication.republished_at = now
        if topic:
            publication.topic = topic
        session.add(publication)
    session.commit()
