from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.database.models import CorporateAction, DataError, ETLRun, OHLCVDaily, Stock


def _insert_for(session: Session, model: type[Any]):
    return sqlite_insert(model) if session.bind and session.bind.dialect.name == "sqlite" else pg_insert(model)


def upsert_stocks(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    if not values:
        return 0
    statement = _insert_for(session, Stock).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[Stock.symbol],
        set_={
            "company_name": statement.excluded.company_name,
            "sector": statement.excluded.sector,
            "sub_sector": statement.excluded.sub_sector,
            "listing_date": statement.excluded.listing_date,
            "active": statement.excluded.active,
            "updated_at": func.now(),
        },
    )
    session.execute(statement)
    return len(values)


def ensure_stock_symbols(session: Session, symbols: Iterable[str]) -> int:
    """Create inactive placeholders without overwriting synchronized metadata."""

    values = [{"symbol": symbol.upper(), "active": False} for symbol in sorted(set(symbols))]
    if not values:
        return 0
    statement = _insert_for(session, Stock).values(values)
    statement = statement.on_conflict_do_nothing(index_elements=[Stock.symbol])
    session.execute(statement)
    return len(values)


def upsert_ohlcv(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    if not values:
        return 0
    statement = _insert_for(session, OHLCVDaily).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[OHLCVDaily.symbol, OHLCVDaily.trade_date],
        set_={
            "open": statement.excluded.open,
            "high": statement.excluded.high,
            "low": statement.excluded.low,
            "close": statement.excluded.close,
            "volume": statement.excluded.volume,
            "source": statement.excluded.source,
            "ingested_at": func.now(),
        },
    )
    session.execute(statement)
    return len(values)


def upsert_corporate_actions(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    if not values:
        return 0
    statement = _insert_for(session, CorporateAction).values(values)
    update_values = {
        "ratio": statement.excluded.ratio,
        "raw_payload": statement.excluded.raw_payload,
    }
    if session.bind and session.bind.dialect.name == "postgresql":
        statement = statement.on_conflict_do_update(
            constraint="uq_corporate_action", set_=update_values
        )
    else:
        statement = statement.on_conflict_do_update(
            index_elements=[
                CorporateAction.symbol,
                CorporateAction.ex_date,
                CorporateAction.action_type,
                CorporateAction.source_id,
            ],
            set_=update_values,
        )
    session.execute(statement)
    return len(values)


def record_data_errors(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    if values:
        session.execute(_insert_for(session, DataError).values(values))
    return len(values)


def last_trade_date(session: Session, symbol: str) -> date | None:
    return session.scalar(select(func.max(OHLCVDaily.trade_date)).where(OHLCVDaily.symbol == symbol))


def latest_market_date(session: Session) -> date | None:
    return session.scalar(select(func.max(OHLCVDaily.trade_date)))


def active_symbols(session: Session) -> list[Stock]:
    return list(session.scalars(select(Stock).where(Stock.active.is_(True)).order_by(Stock.symbol)))


def start_etl_run(session: Session, job_name: str) -> ETLRun:
    run = ETLRun(job_name=job_name, status="RUNNING", rows_loaded=0, rows_rejected=0)
    session.add(run)
    session.flush()
    return run


def finish_etl_run(
    session: Session,
    run: ETLRun,
    *,
    status: str,
    rows_loaded: int,
    rows_rejected: int = 0,
    error_message: str | None = None,
) -> None:
    run.finished_at = datetime.now(timezone.utc)
    run.status = status
    run.rows_loaded = rows_loaded
    run.rows_rejected = rows_rejected
    run.error_message = error_message


def ohlcv_query(symbol: str, from_date: date | None = None, to_date: date | None = None) -> Select:
    statement = select(OHLCVDaily).where(OHLCVDaily.symbol == symbol.upper())
    if from_date:
        statement = statement.where(OHLCVDaily.trade_date >= from_date)
    if to_date:
        statement = statement.where(OHLCVDaily.trade_date <= to_date)
    return statement.order_by(OHLCVDaily.trade_date)
