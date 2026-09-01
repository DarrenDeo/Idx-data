from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy.orm import Session

from app.database.queries import upsert_corporate_actions
from app.downloader.provider import MarketDataProvider


async def sync_corporate_actions(
    session: Session,
    provider: MarketDataProvider,
    symbols: list[str],
    start_date: date,
    end_date: date,
    *,
    concurrency: int = 5,
) -> dict[str, int]:
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch(symbol: str):
        async with semaphore:
            try:
                return await provider.get_corporate_actions(symbol, start_date, end_date), None
            except Exception as exc:
                return [], exc

    loaded = failures = 0
    for task in asyncio.as_completed([asyncio.create_task(fetch(symbol)) for symbol in symbols]):
        actions, error = await task
        if error:
            failures += 1
            continue
        loaded += upsert_corporate_actions(
            session,
            [
                {
                    "symbol": action.symbol,
                    "ex_date": action.ex_date,
                    "action_type": action.action_type,
                    "ratio": action.ratio,
                    "source_id": action.source_id,
                    "raw_payload": action.raw,
                }
                for action in actions
            ],
        )
        session.commit()
    return {"rows_loaded": loaded, "symbols_failed": failures}

