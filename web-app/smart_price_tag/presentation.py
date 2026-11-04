"""Formatting for the interface: Brasília time, published messages and telemetry labels.

Pure functions over stored values; no database access and no secrets.
"""

import json
from datetime import datetime, timedelta, timezone

from .catalog import format_price
from .db import Publication
from .publisher import REASONS

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    BRASILIA = ZoneInfo("America/Sao_Paulo")
except (ImportError, ZoneInfoNotFoundError):  # Windows without the tzdata package
    # Brazil has not used daylight saving time since 2019.
    BRASILIA = timezone(timedelta(hours=-3), "BRT")

# Heuristic thresholds, documented in README: not a link-quality measurement.
RSSI_GOOD_DBM = -67
RSSI_FAIR_DBM = -80


def local_timestamp(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, BRASILIA).strftime("%d/%m/%Y %H:%M") + " (Brasília)"


def relative_time(timestamp: int, now: int) -> str:
    delta = now - timestamp
    future = delta < 0
    seconds = abs(delta)
    if seconds < 60:
        return "agora há pouco" if not future else "em instantes"
    if seconds < 3600:
        amount = f"{seconds // 60} min"
    elif seconds < 2 * 86400:
        amount = f"{seconds // 3600} h"
    else:
        amount = f"{seconds // 86400} dias"
    return f"em {amount}" if future else f"há {amount}"


def local_with_relative(timestamp: int | None, now: int, empty: str = "—") -> str:
    if timestamp is None:
        return empty
    return f"{local_timestamp(timestamp)} · {relative_time(timestamp, now)}"


def group_hex(value: str, size: int = 4) -> str:
    return " ".join(value[index:index + size] for index in range(0, len(value), size))


def money(cents: int) -> str:
    return f"R$ {format_price(cents)}"


def rssi_quality(rssi: int | None) -> tuple[str, str]:
    """Heuristic label: good ≥ −67 dBm, fair down to −80 dBm, weak below."""
    if rssi is None or rssi == 0:
        return "unknown", "Sem leitura"
    if rssi >= RSSI_GOOD_DBM:
        return "good", "Sinal bom"
    if rssi >= RSSI_FAIR_DBM:
        return "fair", "Sinal regular"
    return "weak", "Sinal fraco"


def battery_status(battery_mv: int | None, low_mv: int) -> tuple[str, str]:
    if battery_mv is None:
        return "unknown", "Sem leitura (alimentada só pelo USB ou sem medição)"
    if battery_mv < low_mv:
        return "low", f"Tensão baixa: abaixo de {low_mv} mV"
    return "ok", f"Acima do alerta de {low_mv} mV"


def contact_status(last_received_at: int | None, now: int, interval_s: int, margin_s: int) -> dict[str, str]:
    """Whether the last status is older than the expected wake interval plus a margin."""
    limit = interval_s + margin_s
    window = relative_window(limit)
    if last_received_at is None:
        return {"contact_state": "never", "contact_label": "Nunca enviou status",
                "contact_description": f"Espera-se um status a cada despertar (até {window})."}
    if now - last_received_at > limit:
        return {"contact_state": "late", "contact_label": f"Atrasada: sem status há mais de {window}",
                "contact_description": "A etiqueta não enviou status no intervalo esperado de despertar. Confira bateria, Wi-Fi e broker."}
    return {"contact_state": "ok", "contact_label": "Dentro do intervalo esperado",
            "contact_description": f"Último status há menos de {window}. Isso não indica conexão ativa agora: a etiqueta dorme entre os despertares."}


def relative_window(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    if seconds >= 3600:
        return f"{seconds // 3600} h {seconds % 3600 // 60} min"
    return f"{max(1, seconds // 60)} min"


def _parse_data(data: str) -> dict | None:
    try:
        value = json.loads(data)
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def readable_data(data: str, now: int) -> dict[str, str]:
    """`dados` as the operator reads it: prices in R$, promotion end in Brasília time."""
    body = _parse_data(data) or {}
    product = body.get("produto")
    promotion = body.get("promocao")
    if not isinstance(product, dict):
        return {"pub_name": "Sem produto (etiqueta limpa)", "pub_price": "—", "pub_description": "—", "pub_ean13": "—", "pub_promotion": "—"}
    if isinstance(promotion, dict):
        ends = promotion.get("expira_em", 0)
        verb = "até" if ends > now else "encerrada em"
        promotion_text = f"{money(promotion.get('preco', 0))} {verb} {local_timestamp(ends)}"
    else:
        promotion_text = "Sem promoção"
    return {
        "pub_name": str(product.get("nome", "")),
        "pub_price": money(product.get("preco", 0)),
        "pub_description": str(product.get("descricao", "")) or "—",
        "pub_ean13": str(product.get("ean13", "")),
        "pub_promotion": promotion_text,
    }


def describe_changes(previous: str | None, current: str) -> list[str]:
    """What changed from one signed `dados` to the next, in operator terms."""
    new = _parse_data(current)
    old = _parse_data(previous) if previous is not None else None
    if new is None:
        return []
    if old is None:
        return ["primeira mensagem registrada"]
    changes: list[str] = []
    old_product, new_product = old.get("produto"), new.get("produto")
    if old_product is None and new_product is not None:
        changes.append(f"produto vinculado: {new_product.get('nome', '')}")
    elif old_product is not None and new_product is None:
        changes.append("produto desvinculado (etiqueta limpa)")
    elif isinstance(old_product, dict) and isinstance(new_product, dict):
        if old_product.get("ean13") != new_product.get("ean13") and old_product.get("nome") != new_product.get("nome"):
            changes.append(f"produto trocado: {old_product.get('nome', '')} → {new_product.get('nome', '')}")
        else:
            if old_product.get("nome") != new_product.get("nome"):
                changes.append(f"nome {old_product.get('nome', '')} → {new_product.get('nome', '')}")
            if old_product.get("ean13") != new_product.get("ean13"):
                changes.append(f"EAN-13 {old_product.get('ean13', '')} → {new_product.get('ean13', '')}")
        if old_product.get("preco") != new_product.get("preco"):
            changes.append(f"preço {money(old_product.get('preco', 0))} → {money(new_product.get('preco', 0))}")
        if old_product.get("descricao") != new_product.get("descricao"):
            changes.append("descrição alterada")
    old_promo, new_promo = old.get("promocao"), new.get("promocao")
    if old_promo is None and isinstance(new_promo, dict):
        changes.append(f"promoção criada: {money(new_promo.get('preco', 0))}")
    elif isinstance(old_promo, dict) and new_promo is None and new_product is not None:
        changes.append("promoção removida")
    elif isinstance(old_promo, dict) and isinstance(new_promo, dict):
        if old_promo.get("preco") != new_promo.get("preco"):
            changes.append(f"promoção {money(old_promo.get('preco', 0))} → {money(new_promo.get('preco', 0))}")
        if old_promo.get("expira_em") != new_promo.get("expira_em"):
            changes.append(f"término da promoção → {local_timestamp(new_promo.get('expira_em', 0))}")
    return changes or ["mesmo conteúdo, nova assinatura"]


def publication_summary(publication: Publication, previous_data: str | None, now: int, *, superseded: bool = False) -> dict[str, str | int | list[str]]:
    """One history row; JSON-safe. `superseded`: a newer seq exists, so a missing ACK will not come."""
    unpublished = "Não enviada: substituída pela seguinte" if superseded else "Aguardando ACK do broker"
    return {
        "seq": publication.sequence,
        "version": publication.version,
        "reason": REASONS.get(publication.reason, publication.reason),
        "prepared": local_with_relative(publication.prepared_at, now),
        "published": local_with_relative(publication.published_at, now, unpublished),
        "republished": local_with_relative(publication.republished_at, now, ""),
        "changes": describe_changes(previous_data, publication.data),
    }
