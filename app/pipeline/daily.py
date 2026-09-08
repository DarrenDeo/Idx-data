from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.database.queries import latest_market_date
from app.downloader.provider import MarketDataProvider
from app.pipeline.backfill import backfill_ohlcv
from app.pipeline.index_summary import backfill_index_summary


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
    result = await backfill_ohlcv(
        session,
        provider,
        None,
        start_date,
        end_date,
        concurrency=concurrency,
        job_name="daily_market_update",
    )
    # The public index endpoint is independent of the stock-summary endpoint.
    # Keep it best-effort so an IDX index outage does not discard valid candles.
    try:
        index_result = await backfill_index_summary(
            session,
            provider,
            start_date,
            end_date,
            concurrency=min(2, concurrency),
            job_name="daily_index_summary",
        )
        result["index_rows_loaded"] = index_result["rows_loaded"]
        result["index_dates_failed"] = index_result["dates_failed"]
    except NotImplementedError:
        result["index_rows_loaded"] = 0
        result["index_dates_failed"] = 0
    return result
