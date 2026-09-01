from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.database.queries import latest_market_date
from app.downloader.provider import MarketDataProvider
from app.pipeline.backfill import backfill_ohlcv


def next_market_start(last_date: date | None, requested_end: date) -> date | None:
    candidate = last_date + timedelta(days=1) if last_date else requested_end
    return candidate if candidate <= requested_end else None


async def daily_market_update(
    session: Session,
    provider: MarketDataProvider,
    end_date: date,
    *,
    concurrency: int = 5,
) -> dict[str, int]:
    start_date = next_market_start(latest_market_date(session), end_date)
    if start_date is None:
        return {
            "rows_loaded": 0,
            "rows_rejected": 0,
            "rows_skipped": 0,
            "symbols_failed": 0,
        }
    return await backfill_ohlcv(
        session,
        provider,
        None,
        start_date,
        end_date,
        concurrency=concurrency,
        job_name="daily_market_update",
    )
