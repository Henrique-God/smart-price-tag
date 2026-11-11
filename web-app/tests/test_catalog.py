from datetime import datetime, timezone

import pytest
from sqlmodel import Session

from smart_price_tag.catalog import CatalogError, format_brasilia_input, save_product, save_promotion
from smart_price_tag.db import create_tables, make_engine


def test_promotion_brasilia_conversion_and_future_boundary(tmp_path):
    engine = make_engine(tmp_path / "catalog.db")
    create_tables(engine)
    with Session(engine) as session:
        product = save_product(session, product_id=None, name="Produto teste", price="999,99", description="Teste", ean13="7891234567895")
        now = datetime(2026, 11, 11, 23, 59, tzinfo=timezone.utc)
        save_promotion(session, product.id, "0,01", "2026-11-11T21:00", now=now)
        expected = int(datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc).timestamp())
        assert product.promotion_price_cents == 1
        assert product.promotion_ends_at == expected
        assert format_brasilia_input(expected) == "2026-11-11T21:00"
        for price, ends_at in [("0,01", "2026-11-11T20:59"), ("1000,00", "2026-11-12T21:00"), ("1,00", "2026-02-30T12:00")]:
            with pytest.raises(CatalogError):
                save_promotion(session, product.id, price, ends_at, now=now)
        assert product.promotion_ends_at == expected
