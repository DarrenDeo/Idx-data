from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.database.queries import (
    active_symbols,
    ensure_stock_symbols,
    finish_etl_run,
    record_data_errors,
    start_etl_run,
    upsert_ohlcv,
)
from app.downloader.provider import MarketDataProvider, OHLCVRecord
from app.monitoring import record_etl_result
from app.validation.ohlcv import is_no_trade, validate_batch

log = logging.getLogger(__name__)


def _row(record: OHLCVRecord) -> dict[str, Any]:
    return {
        "symbol": record.symbol,
        "trade_date": record.trade_date,
        "open": record.open,
        "high": record.high,
        "low": record.low,
        "close": record.close,
        "volume": record.volume,
        "source": record.source,
    }


async def backfill_ohlcv(
    session: Session,
    provider: MarketDataProvider,
    symbols: list[str] | None,
    start_date: date,
    end_date: date,
    *,
    concurrency: int = 5,
    job_name: str = "backfill_ohlcv",
) -> dict[str, int]:
    run = start_etl_run(session, job_name)
    session.commit()
    try:
        if provider.supports_daily_bulk_backfill:
            loaded, rejected, failures, skipped = await _backfill_by_trading_date(
                session,
                provider,
                symbols,
                start_date,
                end_date,
                concurrency,
            )
            failure_unit = "date"
        else:
            selected_symbols = symbols or [stock.symbol for stock in active_symbols(session)]
            loaded, rejected, failures, skipped = await _backfill_by_symbol(
                session,
                provider,
                selected_symbols,
                start_date,
                end_date,
                concurrency,
            )
            failure_unit = "symbol"
    except asyncio.CancelledError:
        session.rollback()
        stored_run = session.get(type(run), run.id)
        finish_etl_run(
            session,
            stored_run,
            status="CANCELLED",
            rows_loaded=0,
            rows_rejected=0,
            error_message="operator interrupted the run",
        )
        session.commit()
        record_etl_result(job_name, "CANCELLED", 0)
        log.warning("Backfill cancelled range=%s..%s", start_date, end_date)
        raise

    stored_run = session.get(type(run), run.id)
    final_status = "SUCCESS" if failures == 0 else "PARTIAL"
    finish_etl_run(
        session,
        stored_run,
        status=final_status,
        rows_loaded=loaded,
        rows_rejected=rejected,
        error_message=f"{failures} {failure_unit}(s) failed" if failures else None,
    )
    session.commit()
    record_etl_result(job_name, final_status, loaded)
    return {
        "rows_loaded": loaded,
        "rows_rejected": rejected,
        "rows_skipped": skipped,
        "symbols_failed": failures,
    }


def _weekdays(start_date: date, end_date: date) -> list[date]:
    dates: list[date] = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates


async def _backfill_by_trading_date(
    session: Session,
    provider: MarketDataProvider,
    symbols: list[str] | None,
    start_date: date,
    end_date: date,
    concurrency: int,
) -> tuple[int, int, int, int]:
    """Fetch one all-market payload per weekday and persist requested symbols."""

    requested = {symbol.upper() for symbol in symbols} if symbols is not None else None
    loaded = rejected = failures = skipped = 0

    async def fetch_day(trade_date: date):
        try:
            return trade_date, await provider.get_daily_market_data(trade_date), None
        except Exception as exc:  # isolate one date from all other progress
            return trade_date, [], exc

    dates = _weekdays(start_date, end_date)
    for offset in range(0, len(dates), concurrency):
        chunk = dates[offset : offset + concurrency]
        results = await asyncio.gather(*(fetch_day(trade_date) for trade_date in chunk))
        for trade_date, records, error in results:
            if error:
                failures += 1
                record_data_errors(
                    session,
                    [
                        {
                            "symbol": None,
                            "trade_date": trade_date,
                            "error_message": f"daily provider failure: {error}",
                            "raw_payload": {
                                "symbols": sorted(requested) if requested is not None else "ALL"
                            },
                        }
                    ],
                )
                session.commit()
                log.error("Backfill failed date=%s error=%s", trade_date, error)
                continue

            selected = (
                records
                if requested is None
                else [record for record in records if record.symbol.upper() in requested]
            )
            trade_rows = [record for record in selected if not is_no_trade(record)]
            date_skipped = len(selected) - len(trade_rows)
            valid, errors = validate_batch(trade_rows)
            try:
                ensure_stock_symbols(session, (record.symbol for record in valid))
                date_loaded = upsert_ohlcv(session, [_row(record) for record in valid])
                date_rejected = record_data_errors(session, errors)
                session.commit()
                loaded += date_loaded
                rejected += date_rejected
                skipped += date_skipped
            except Exception as exc:
                session.rollback()
                failures += 1
                record_data_errors(
                    session,
                    [
                        {
                            "symbol": None,
                            "trade_date": trade_date,
                            "error_message": f"daily persistence failure: {exc}",
                            "raw_payload": {
                                "symbols": sorted(requested) if requested is not None else "ALL"
                            },
                        }
                    ],
                )
                session.commit()
                log.error("Backfill persistence failed date=%s error=%s", trade_date, exc)
                continue
            log.info(
                "Backfill date=%s market_rows=%d selected=%d loaded=%d rejected=%d skipped=%d",
                trade_date,
                len(records),
                len(selected),
                date_loaded,
                date_rejected,
                date_skipped,
            )

    return loaded, rejected, failures, skipped


async def _backfill_by_symbol(
    session: Session,
    provider: MarketDataProvider,
    symbols: list[str],
    start_date: date,
    end_date: date,
    concurrency: int,
) -> tuple[int, int, int, int]:
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch(symbol: str):
        async with semaphore:
            try:
                return symbol, await provider.get_ohlcv(symbol, start_date, end_date), None
            except Exception as exc:  # isolate one symbol from all other progress
                return symbol, [], exc

    loaded = rejected = failures = skipped = 0
    tasks = [asyncio.create_task(fetch(symbol.upper())) for symbol in symbols]
    for task in asyncio.as_completed(tasks):
        symbol, records, error = await task
        if error:
            failures += 1
            record_data_errors(
                session,
                [
                    {
                        "symbol": symbol,
                        "trade_date": None,
                        "error_message": f"provider failure: {error}",
                        "raw_payload": {"start": str(start_date), "end": str(end_date)},
                    }
                ],
            )
            session.commit()
            log.error("Backfill failed symbol=%s error=%s", symbol, error)
            continue

        trade_rows = [record for record in records if not is_no_trade(record)]
        symbol_skipped = len(records) - len(trade_rows)
        valid, errors = validate_batch(trade_rows)
        try:
            symbol_loaded = upsert_ohlcv(session, [_row(record) for record in valid])
            symbol_rejected = record_data_errors(session, errors)
            session.commit()
            loaded += symbol_loaded
            rejected += symbol_rejected
            skipped += symbol_skipped
        except Exception as exc:
            session.rollback()
            failures += 1
            record_data_errors(
                session,
                [
                    {
                        "symbol": symbol,
                        "trade_date": None,
                        "error_message": f"persistence failure: {exc}",
                        "raw_payload": {"start": str(start_date), "end": str(end_date)},
                    }
                ],
            )
            session.commit()
            log.error("Backfill persistence failed symbol=%s error=%s", symbol, exc)
            continue
        log.info(
            "Backfill symbol=%s range=%s..%s fetched=%d loaded=%d rejected=%d skipped=%d",
            symbol,
            start_date,
            end_date,
            len(records),
            len(valid),
            len(errors),
            symbol_skipped,
        )

    return loaded, rejected, failures, skipped
