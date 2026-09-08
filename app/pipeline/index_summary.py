"""Fetch and persist daily IDX index summaries."""

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
    upsert_benchmarks,
    upsert_index_summary,
)
from app.downloader.provider import IndexSummaryRecord, MarketDataProvider
from app.monitoring import record_etl_result

log = logging.getLogger(__name__)

# A 20-session benchmark return needs the current close plus 20 earlier
# observations.  A calendar buffer also leaves room for IDX holidays and
# other non-trading days, so a short UI date range still has enough history
# for the regime/probability calculations.
BENCHMARK_REQUIRED_OBSERVATIONS = 21
BENCHMARK_LOOKBACK_CALENDAR_DAYS = 60


def benchmark_backfill_start(
    requested_start: date,
    *,
    required_observations: int = BENCHMARK_REQUIRED_OBSERVATIONS,
) -> date:
    """Return a safe benchmark start date for a requested analysis range.

    The extra calendar padding is intentional: the public IDX index feed does
    not expose a holiday calendar, and a weekday-only subtraction could still
    leave fewer than 21 actual observations after holidays or feed gaps.
    """

    if required_observations < 1:
        raise ValueError("required_observations must be positive")
    calendar_days = max(BENCHMARK_LOOKBACK_CALENDAR_DAYS, required_observations * 2)
    return requested_start - timedelta(days=calendar_days)


def _weekdays(start_date: date, end_date: date) -> list[date]:
    result: list[date] = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def _number(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    try:
        return int(float(value)) if isinstance(default, int) else value
    except (TypeError, ValueError):
        return default


def _index_row(record: IndexSummaryRecord) -> dict[str, Any]:
    return {
        "benchmark": record.benchmark,
        "trade_date": record.trade_date,
        "previous": record.previous,
        "highest": record.highest,
        "lowest": record.lowest,
        "close": record.close,
        "change": record.change,
        "number_of_stock": _number(record.number_of_stock, 0),
        "volume": _number(record.volume, 0),
        "value": record.value,
        "frequency": _number(record.frequency, 0),
        "source": record.source,
        "raw_payload": record.raw,
    }


def _benchmark_row(record: IndexSummaryRecord) -> dict[str, Any]:
    return {
        "benchmark": "IHSG" if record.benchmark in {"COMPOSITE", "IHSG"} else record.benchmark,
        "trade_date": record.trade_date,
        "open": record.previous,
        "high": record.highest,
        "low": record.lowest,
        "close": record.close,
        "volume": _number(record.volume, 0),
        "source": record.source,
    }


async def backfill_index_summary(
    session: Session,
    provider: MarketDataProvider,
    start_date: date,
    end_date: date,
    *,
    concurrency: int = 2,
    job_name: str = "index_summary",
) -> dict[str, int]:
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    run = start_etl_run(session, job_name)
    session.commit()
    loaded = failures = 0
    dates = _weekdays(start_date, end_date)

    async def fetch(day: date):
        try:
            return day, await provider.get_index_summary(day), None
        except Exception as exc:
            return day, [], exc

    try:
        for offset in range(0, len(dates), max(1, concurrency)):
            results = await asyncio.gather(*(fetch(day) for day in dates[offset : offset + max(1, concurrency)]))
            for trade_date, records, error in results:
                if error:
                    failures += 1
                    record_data_errors(session, [{
                        "symbol": None,
                        "trade_date": trade_date,
                        "error_message": f"index provider failure: {error}",
                        "raw_payload": {"dataset": "index_summary"},
                    }])
                    session.commit()
                    continue
                try:
                    rows = [_index_row(record) for record in records if record.close not in (None, "")]
                    upsert_index_summary(session, rows)
                    # BenchmarkDaily remains the compatibility surface used by
                    # existing analytics and exports.
                    upsert_benchmarks(session, [_benchmark_row(record) for record in records if record.close not in (None, "")])
                    session.commit()
                    loaded += len(rows)
                except Exception as exc:
                    session.rollback()
                    failures += 1
                    record_data_errors(session, [{
                        "symbol": None,
                        "trade_date": trade_date,
                        "error_message": f"index persistence failure: {exc}",
                        "raw_payload": {"dataset": "index_summary"},
                    }])
                    session.commit()
                    log.exception("Index persistence failed for %s", trade_date)
    except asyncio.CancelledError:
        session.rollback()
        stored_run = session.get(type(run), run.id)
        finish_etl_run(session, stored_run, status="CANCELLED", rows_loaded=loaded, rows_rejected=0, error_message="operator interrupted the run")
        session.commit()
        record_etl_result(job_name, "CANCELLED", loaded)
        raise

    stored_run = session.get(type(run), run.id)
    status = "SUCCESS" if failures == 0 else "PARTIAL"
    finish_etl_run(session, stored_run, status=status, rows_loaded=loaded, rows_rejected=0, error_message=f"{failures} date(s) failed" if failures else None)
    session.commit()
    record_etl_result(job_name, status, loaded)
    return {"rows_loaded": loaded, "rows_rejected": 0, "dates_failed": failures}
