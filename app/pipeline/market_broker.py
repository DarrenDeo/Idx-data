from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.database.queries import (
    finish_etl_run,
    record_data_errors,
    start_etl_run,
    upsert_market_broker_summary,
)
from app.downloader.provider import MarketBrokerSummaryRecord, MarketDataProvider
from app.monitoring import record_etl_result

log = logging.getLogger(__name__)


def _weekdays(start_date: date, end_date: date) -> list[date]:
    days: list[date] = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _row(record: MarketBrokerSummaryRecord) -> dict[str, Any]:
    return {
        "trade_date": record.trade_date,
        "broker_code": record.broker_code,
        "broker_name": record.broker_name,
        "volume": record.volume,
        "value": record.value,
        "frequency": record.frequency,
        "source": record.source,
    }


async def backfill_market_broker_summary(
    session: Session,
    provider: MarketDataProvider,
    start_date: date,
    end_date: date,
    *,
    concurrency: int = 1,
    job_name: str = "market_broker_summary",
) -> dict[str, int]:
    """Fetch and persist IDX's market-wide broker summary by trading date."""

    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    run = start_etl_run(session, job_name)
    session.commit()
    loaded = failures = 0
    try:
        dates = _weekdays(start_date, end_date)
        concurrency = max(1, concurrency)

        async def fetch_day(trade_date: date):
            try:
                return trade_date, await provider.get_market_broker_summary(trade_date), None
            except Exception as exc:  # isolate one date from the remaining range
                return trade_date, [], exc

        for offset in range(0, len(dates), concurrency):
            batch = dates[offset : offset + concurrency]
            results = await asyncio.gather(*(fetch_day(day) for day in batch))
            for trade_date, records, error in results:
                if error:
                    failures += 1
                    record_data_errors(
                        session,
                        [
                            {
                                "symbol": None,
                                "trade_date": trade_date,
                                "error_message": f"market broker provider failure: {error}",
                                "raw_payload": {"dataset": "market_broker_summary"},
                            }
                        ],
                    )
                    session.commit()
                    log.error("Market broker summary failed date=%s error=%s", trade_date, error)
                    continue
                try:
                    loaded_for_day = upsert_market_broker_summary(
                        session, [_row(record) for record in records]
                    )
                    session.commit()
                    loaded += loaded_for_day
                    log.info(
                        "Market broker summary date=%s rows=%d loaded=%d",
                        trade_date,
                        len(records),
                        loaded_for_day,
                    )
                except Exception as exc:
                    session.rollback()
                    failures += 1
                    record_data_errors(
                        session,
                        [
                            {
                                "symbol": None,
                                "trade_date": trade_date,
                                "error_message": f"market broker persistence failure: {exc}",
                                "raw_payload": {"dataset": "market_broker_summary"},
                            }
                        ],
                    )
                    session.commit()
                    log.error("Market broker persistence failed date=%s error=%s", trade_date, exc)
    except asyncio.CancelledError:
        session.rollback()
        stored_run = session.get(type(run), run.id)
        finish_etl_run(
            session,
            stored_run,
            status="CANCELLED",
            rows_loaded=loaded,
            rows_rejected=0,
            error_message="operator interrupted the run",
        )
        session.commit()
        record_etl_result(job_name, "CANCELLED", loaded)
        raise

    stored_run = session.get(type(run), run.id)
    status = "SUCCESS" if failures == 0 else "PARTIAL"
    finish_etl_run(
        session,
        stored_run,
        status=status,
        rows_loaded=loaded,
        rows_rejected=0,
        error_message=f"{failures} date(s) failed" if failures else None,
    )
    session.commit()
    record_etl_result(job_name, status, loaded)
    return {"rows_loaded": loaded, "rows_rejected": 0, "dates_failed": failures}
