from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.database.models import (
    BenchmarkDaily,
    BrokerSummaryDaily,
    CorporateAction,
    DataError,
    ETLRun,
    ForeignFlowDaily,
    FundamentalQuarterly,
    IndexSummaryDaily,
    IntradayTrade,
    MarketBrokerSummaryDaily,
    MarketEvent,
    MarketNews,
    OHLCVDaily,
    OrderBookSnapshot,
    Stock,
    StockSummaryDaily,
)


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


def upsert_stock_summary(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    if not values:
        return 0
    statement = _insert_for(session, StockSummaryDaily).values(values)
    update_columns = (
        "company_name", "previous", "open_price", "first_trade", "high", "low", "close",
        "change", "volume", "value", "frequency", "foreign_buy_volume", "foreign_sell_volume",
        "non_regular_volume", "non_regular_value", "non_regular_frequency", "listed_shares",
        "tradeable_shares", "weight_for_index", "index_individual", "source", "raw_payload",
    )
    statement = statement.on_conflict_do_update(
        index_elements=[StockSummaryDaily.symbol, StockSummaryDaily.trade_date],
        set_={column: getattr(statement.excluded, column) for column in update_columns}
        | {"ingested_at": func.now()},
    )
    session.execute(statement)
    return len(values)


def upsert_benchmarks(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    if not values:
        return 0
    statement = _insert_for(session, BenchmarkDaily).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[BenchmarkDaily.benchmark, BenchmarkDaily.trade_date],
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


def upsert_index_summary(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    if not values:
        return 0
    statement = _insert_for(session, IndexSummaryDaily).values(values)
    update_columns = (
        "previous", "highest", "lowest", "close", "change", "number_of_stock", "volume",
        "value", "frequency", "source", "raw_payload",
    )
    statement = statement.on_conflict_do_update(
        index_elements=[IndexSummaryDaily.benchmark, IndexSummaryDaily.trade_date],
        set_={column: getattr(statement.excluded, column) for column in update_columns}
        | {"ingested_at": func.now()},
    )
    session.execute(statement)
    return len(values)


def upsert_foreign_flow(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    if not values:
        return 0
    statement = _insert_for(session, ForeignFlowDaily).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[ForeignFlowDaily.symbol, ForeignFlowDaily.trade_date],
        set_={
            column: getattr(statement.excluded, column)
            for column in (
                "foreign_buy_volume",
                "foreign_sell_volume",
                "foreign_buy_value",
                "foreign_sell_value",
                "foreign_net_value",
                "foreign_average_buy",
                "foreign_average_sell",
                "source",
            )
        }
        | {"ingested_at": func.now()},
    )
    session.execute(statement)
    return len(values)


def upsert_broker_summary(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    if not values:
        return 0
    statement = _insert_for(session, BrokerSummaryDaily).values(values)
    update_columns = (
        "broker_name",
        "buy_volume",
        "sell_volume",
        "buy_value",
        "sell_value",
        "buy_average",
        "sell_average",
        "net_volume",
        "net_value",
        "buy_frequency",
        "sell_frequency",
        "source",
    )
    statement = statement.on_conflict_do_update(
        index_elements=[
            BrokerSummaryDaily.symbol,
            BrokerSummaryDaily.trade_date,
            BrokerSummaryDaily.broker_code,
        ],
        set_={column: getattr(statement.excluded, column) for column in update_columns}
        | {"ingested_at": func.now()},
    )
    session.execute(statement)
    return len(values)


def upsert_market_broker_summary(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    if not values:
        return 0
    statement = _insert_for(session, MarketBrokerSummaryDaily).values(values)
    update_columns = ("broker_name", "volume", "value", "frequency", "source")
    statement = statement.on_conflict_do_update(
        index_elements=[
            MarketBrokerSummaryDaily.trade_date,
            MarketBrokerSummaryDaily.broker_code,
        ],
        set_={column: getattr(statement.excluded, column) for column in update_columns}
        | {"ingested_at": func.now()},
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


def _upsert_rows(
    session: Session,
    model: type[Any],
    rows: Iterable[dict[str, Any]],
    index_elements: list[Any],
    update_columns: tuple[str, ...],
) -> int:
    values = list(rows)
    if not values:
        return 0
    statement = _insert_for(session, model).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=index_elements,
        set_={column: getattr(statement.excluded, column) for column in update_columns},
    )
    session.execute(statement)
    return len(values)


def upsert_order_book(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    return _upsert_rows(
        session, OrderBookSnapshot, rows,
        [OrderBookSnapshot.symbol, OrderBookSnapshot.captured_at, OrderBookSnapshot.level],
        ("bid_price", "bid_volume", "offer_price", "offer_volume", "indicative_price", "source", "raw_payload"),
    )


def upsert_intraday_trades(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    return _upsert_rows(
        session, IntradayTrade, rows,
        [IntradayTrade.symbol, IntradayTrade.traded_at, IntradayTrade.sequence],
        ("price", "volume", "buyer_broker", "seller_broker", "source", "raw_payload"),
    )


def upsert_fundamentals(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    return _upsert_rows(
        session, FundamentalQuarterly, rows,
        [FundamentalQuarterly.symbol, FundamentalQuarterly.fiscal_year, FundamentalQuarterly.fiscal_quarter],
        (
            "report_date", "revenue", "ebitda", "net_income", "operating_cash_flow", "capex",
            "cash", "debt", "shares_outstanding", "segment_revenue", "major_ownership", "source", "raw_payload",
        ),
    )


def upsert_market_events(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    if not values:
        return 0
    loaded = 0
    for row in values:
        existing = session.scalar(
            select(MarketEvent).where(
                MarketEvent.symbol == row.get("symbol"),
                MarketEvent.event_date == row["event_date"],
                MarketEvent.event_type == row["event_type"],
                MarketEvent.source_id == row.get("source_id", ""),
            )
        )
        if existing:
            for key, value in row.items():
                if key != "id":
                    setattr(existing, key, value)
        else:
            session.add(MarketEvent(**row))
        loaded += 1
    return loaded


def upsert_market_news(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    if not values:
        return 0
    loaded = 0
    for row in values:
        existing = session.scalar(
            select(MarketNews).where(
                MarketNews.symbol == row.get("symbol"),
                MarketNews.published_at == row["published_at"],
                MarketNews.title == row["title"],
            )
        )
        if existing:
            for key, value in row.items():
                if key != "id":
                    setattr(existing, key, value)
        else:
            session.add(MarketNews(**row))
        loaded += 1
    return loaded


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
