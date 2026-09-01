from datetime import date

import pytest
from sqlalchemy import func, select

from app.database.models import DataError, OHLCVDaily, Stock
from app.database.queries import upsert_stocks
from app.downloader.provider import CorporateActionRecord, MarketDataProvider, OHLCVRecord, SymbolRecord
from app.pipeline.backfill import backfill_ohlcv


class StaticProvider(MarketDataProvider):
    async def get_symbols(self):
        return [SymbolRecord("BBCA")]

    async def get_ohlcv(self, symbol, start_date, end_date):
        return [OHLCVRecord(symbol, start_date, 10, 12, 9, 11, 100, source="test")]

    async def get_daily_market_data(self, trade_date):
        return []

    async def get_corporate_actions(self, symbol, start_date, end_date):
        return [CorporateActionRecord(symbol, start_date, "Stock Split")]


class DailyStaticProvider(StaticProvider):
    supports_daily_bulk_backfill = True

    def __init__(self):
        self.daily_calls = []

    async def get_ohlcv(self, symbol, start_date, end_date):
        raise AssertionError("daily bulk provider must not use per-symbol history")

    async def get_daily_market_data(self, trade_date):
        self.daily_calls.append(trade_date)
        return [
            OHLCVRecord("BBCA", trade_date, 10, 12, 9, 11, 100, source="test"),
            OHLCVRecord("BBRI", trade_date, 20, 22, 19, 21, 200, source="test"),
        ]


class DailyProviderWithNoTradeRow(DailyStaticProvider):
    async def get_daily_market_data(self, trade_date):
        self.daily_calls.append(trade_date)
        return [
            OHLCVRecord("BBCA", trade_date, 10, 12, 9, 11, 100, source="test"),
            OHLCVRecord("BBRI", trade_date, 0, 0, 0, 21, 0, source="test"),
        ]


@pytest.mark.asyncio
async def test_backfill_rerun_is_idempotent(session):
    upsert_stocks(session, [{"symbol": "BBCA", "active": True}])
    session.commit()
    provider = StaticProvider()
    for _ in range(2):
        result = await backfill_ohlcv(
            session,
            provider,
            ["BBCA"],
            date(2026, 8, 28),
            date(2026, 8, 28),
            concurrency=1,
        )
        assert result["symbols_failed"] == 0
    assert session.scalar(select(func.count()).select_from(OHLCVDaily)) == 1


@pytest.mark.asyncio
async def test_daily_bulk_backfill_fetches_market_once_for_multiple_symbols(session):
    upsert_stocks(
        session,
        [
            {"symbol": "BBCA", "active": True},
            {"symbol": "BBRI", "active": True},
        ],
    )
    session.commit()
    provider = DailyStaticProvider()

    result = await backfill_ohlcv(
        session,
        provider,
        ["BBCA", "BBRI"],
        date(2026, 8, 28),
        date(2026, 8, 28),
        concurrency=5,
    )

    assert result == {
        "rows_loaded": 2,
        "rows_rejected": 0,
        "rows_skipped": 0,
        "symbols_failed": 0,
    }
    assert provider.daily_calls == [date(2026, 8, 28)]
    assert session.scalar(select(func.count()).select_from(OHLCVDaily)) == 2


@pytest.mark.asyncio
async def test_unfiltered_daily_backfill_keeps_historical_only_symbols(session):
    upsert_stocks(
        session,
        [{"symbol": "BBCA", "company_name": "Bank Central Asia", "active": True}],
    )
    session.commit()
    provider = DailyStaticProvider()

    result = await backfill_ohlcv(
        session,
        provider,
        None,
        date(2026, 8, 28),
        date(2026, 8, 28),
        concurrency=5,
    )

    assert result["rows_loaded"] == 2
    assert session.get(Stock, "BBCA").company_name == "Bank Central Asia"
    assert session.get(Stock, "BBCA").active is True
    assert session.get(Stock, "BBRI").active is False


@pytest.mark.asyncio
async def test_daily_bulk_backfill_skips_zero_volume_rows_without_recording_errors(session):
    upsert_stocks(
        session,
        [
            {"symbol": "BBCA", "active": True},
            {"symbol": "BBRI", "active": True},
        ],
    )
    session.commit()
    provider = DailyProviderWithNoTradeRow()

    result = await backfill_ohlcv(
        session,
        provider,
        ["BBCA", "BBRI"],
        date(2026, 8, 28),
        date(2026, 8, 28),
        concurrency=5,
    )

    assert result == {
        "rows_loaded": 1,
        "rows_rejected": 0,
        "rows_skipped": 1,
        "symbols_failed": 0,
    }
    assert session.scalar(select(func.count()).select_from(OHLCVDaily)) == 1
    assert session.scalar(select(func.count()).select_from(DataError)) == 0
