from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.database.models import CorporateAction, OHLCVDaily, Stock
from app.database.queries import upsert_corporate_actions, upsert_ohlcv, upsert_stocks


def test_upsert_prevents_duplicates_and_updates(session):
    upsert_stocks(session, [{"symbol": "BBCA", "company_name": "BCA", "active": True}])
    first = {
        "symbol": "BBCA",
        "trade_date": date(2026, 8, 28),
        "open": Decimal("8000"),
        "high": Decimal("8200"),
        "low": Decimal("7900"),
        "close": Decimal("8100"),
        "volume": 100,
        "source": "test",
    }
    upsert_ohlcv(session, [first])
    upsert_ohlcv(session, [{**first, "close": Decimal("8150"), "volume": 200}])
    session.commit()

    assert session.scalar(select(func.count()).select_from(OHLCVDaily)) == 1
    stored = session.get(OHLCVDaily, ("BBCA", date(2026, 8, 28)))
    assert stored.close == Decimal("8150.00")
    assert stored.volume == 200


def test_symbol_upsert_updates_metadata(session):
    upsert_stocks(session, [{"symbol": "BBCA", "company_name": "Old", "active": True}])
    upsert_stocks(session, [{"symbol": "BBCA", "company_name": "New", "active": True}])
    session.commit()
    assert session.get(Stock, "BBCA").company_name == "New"


def test_corporate_action_upsert_is_idempotent(session):
    upsert_stocks(session, [{"symbol": "BBCA", "active": True}])
    action = {
        "symbol": "BBCA",
        "ex_date": date(2026, 8, 28),
        "action_type": "Stock Split",
        "ratio": Decimal("5"),
        "source_id": "123",
        "raw_payload": {"id": 123},
    }
    upsert_corporate_actions(session, [action])
    upsert_corporate_actions(session, [{**action, "ratio": Decimal("10")}])
    session.commit()
    assert session.scalar(select(func.count()).select_from(CorporateAction)) == 1
    assert session.scalar(select(CorporateAction.ratio)) == Decimal("10.0000000000")
