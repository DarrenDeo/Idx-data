from __future__ import annotations

import asyncio
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.database.queries import active_symbols, last_trade_date
from app.downloader.provider import MarketDataProvider
from app.pipeline.backfill import backfill_ohlcv


def next_start_date(
    last_date: date | None, listing_date: date | None, requested_end: date
) -> date | None:
    if last_date:
        candidate = last_date + timedelta(days=1)
    elif listing_date:
        candidate = listing_date
    else:
        candidate = requested_end
    return candidate if candidate <= requested_end else None


async def incremental_update(
    session: Session,
    provider: MarketDataProvider,
    end_date: date,
    *,
    concurrency: int = 5,
) -> dict[str, int]:
    ranges: dict[date, list[str]] = {}
    for stock in active_symbols(session):
        start = next_start_date(last_trade_date(session, stock.symbol), stock.listing_date, end_date)
        if start is not None:
            ranges.setdefault(start, []).append(stock.symbol)

    totals = {
        "rows_loaded": 0,
        "rows_rejected": 0,
        "rows_skipped": 0,
        "symbols_failed": 0,
    }
    # Symbols with the same start date share a bounded batch. This also makes the
    # execution easy to resume because each symbol commits independently.
    for start, symbols in sorted(ranges.items()):
        result = await backfill_ohlcv(
            session,
            provider,
            symbols,
            start,
            end_date,
            concurrency=concurrency,
            job_name="incremental_update",
        )
        for key in totals:
            totals[key] += result[key]
    return totals
