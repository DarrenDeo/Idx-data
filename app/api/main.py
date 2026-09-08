from __future__ import annotations

import csv
import logging
import re
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.api.cache import OptionalCache
from app.api.dashboard import DASHBOARD_HTML
from app.api.jobs import JobAlreadyRunningError, JobCooldownError, job_manager
from app.analytics import analyze_ohlcv
from app.backtesting import summarize_backtest_outcomes, volatility_position_size, walk_forward_backtest
from app.feature_analysis import summarize_events, summarize_fundamentals, summarize_intraday, summarize_order_book
from app.config import settings
from app.data_import import parse_dataset, parse_uploaded_file
from app.database.connection import engine, get_db
from app.database.models import Base
from app.database.models import (
    BenchmarkDaily,
    BrokerSummaryDaily,
    AdjustedPrice,
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
from app.database.queries import (
    ohlcv_query,
    upsert_ohlcv,
    upsert_benchmarks,
    upsert_broker_summary,
    upsert_foreign_flow,
    upsert_fundamentals,
    upsert_index_summary,
    upsert_intraday_trades,
    upsert_market_events,
    upsert_market_news,
    upsert_order_book,
    upsert_stock_summary,
    ensure_stock_symbols,
)
from app.exporting.excel import (
    EXCEL_MIME_TYPE,
    build_analysis_workbook,
    build_broker_workbook,
    build_market_broker_workbook,
    build_table_workbook,
    build_ohlcv_workbook,
)
from app.monitoring import API_LATENCY, API_REQUESTS
from app.pipeline.index_summary import benchmark_backfill_start

log = logging.getLogger(__name__)
MAX_EXPORT_ROWS = 100_000


def _export_symbols(value: str | None) -> list[str] | None:
    if value is None or not value.strip():
        return None
    symbols = sorted({part.upper() for part in re.split(r"[,\s]+", value.strip()) if part})
    invalid = [symbol for symbol in symbols if not re.fullmatch(r"[A-Z0-9.-]{1,16}", symbol)]
    if invalid:
        raise HTTPException(status_code=422, detail=f"invalid symbol: {invalid[0]}")
    if len(symbols) > 200:
        raise HTTPException(status_code=422, detail="at most 200 explicit symbols per export")
    return symbols


def _export_filename(
    symbols: list[str] | None,
    from_date: date | None,
    to_date: date | None,
    extension: str,
) -> str:
    scope = "all" if not symbols else "-".join(symbols[:5])
    if symbols and len(symbols) > 5:
        scope += f"-plus-{len(symbols) - 5}"
    start = from_date.isoformat() if from_date else "first"
    end = to_date.isoformat() if to_date else "latest"
    return f"idx_ohlcv_{scope}_{start}_{end}.{extension}"


class SymbolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    symbol: str
    company_name: str | None
    sector: str | None
    sub_sector: str | None
    listing_date: date | None
    active: bool


class OHLCVOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    symbol: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class OHLCVWithIndicatorsOut(OHLCVOut):
    """Dashboard rows with trading-session moving averages."""

    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    ma50: float | None = None
    ema5: float | None = None
    ema10: float | None = None
    ema20: float | None = None
    ema50: float | None = None
    rsi14: float | None = None
    atr14: float | None = None
    market_regime: str | None = None
    ensemble_score: float | None = None
    entry_signal: str | None = None
    price_source: str | None = None


class ETLRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_name: str
    status: str
    rows_loaded: int
    rows_rejected: int
    error_message: str | None


class DailyJobRequest(BaseModel):
    end: date | None = None


class BackfillJobRequest(BaseModel):
    symbols: str
    start: date
    end: date


class DateRangeJobRequest(BaseModel):
    start: date
    end: date


class SymbolsDateRangeJobRequest(DateRangeJobRequest):
    symbols: str


class SymbolsJobRequest(BaseModel):
    symbols: str


class DatasetImportRequest(BaseModel):
    content: str
    source: str = "import"


def _validate_range(from_date: date | None, to_date: date | None) -> None:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from must not be after to")


def _analysis_rows(
    db: Session,
    symbols: str | None,
    from_date: date | None,
    to_date: date | None,
    limit: int,
) -> list[dict[str, Any]]:
    _validate_range(from_date, to_date)
    selected_symbols = _export_symbols(symbols)
    if not selected_symbols:
        raise HTTPException(status_code=422, detail="Isi minimal satu simbol untuk analisis")
    statement = select(OHLCVDaily).where(OHLCVDaily.symbol.in_(selected_symbols))
    if to_date:
        statement = statement.where(OHLCVDaily.trade_date <= to_date)
    statement = statement.order_by(OHLCVDaily.symbol, OHLCVDaily.trade_date)
    source_rows = list(db.scalars(statement))
    if not source_rows:
        raise HTTPException(status_code=404, detail="no OHLCV rows matched the analysis filters")
    benchmark_statement = select(BenchmarkDaily).where(BenchmarkDaily.benchmark == "IHSG")
    if to_date:
        benchmark_statement = benchmark_statement.where(BenchmarkDaily.trade_date <= to_date)
    benchmark_rows = list(db.scalars(benchmark_statement.order_by(BenchmarkDaily.trade_date)))
    foreign_statement = select(ForeignFlowDaily).where(
        ForeignFlowDaily.symbol.in_(selected_symbols)
    )
    if to_date:
        foreign_statement = foreign_statement.where(ForeignFlowDaily.trade_date <= to_date)
    foreign_rows = list(db.scalars(foreign_statement))
    broker_statement = select(BrokerSummaryDaily).where(
        BrokerSummaryDaily.symbol.in_(selected_symbols)
    )
    if to_date:
        broker_statement = broker_statement.where(BrokerSummaryDaily.trade_date <= to_date)
    broker_rows = list(db.scalars(broker_statement))
    stock_summary_statement = select(StockSummaryDaily).where(
        StockSummaryDaily.symbol.in_(selected_symbols)
    )
    if to_date:
        stock_summary_statement = stock_summary_statement.where(StockSummaryDaily.trade_date <= to_date)
    stock_summary_rows = list(db.scalars(stock_summary_statement))
    adjusted_statement = select(AdjustedPrice).where(AdjustedPrice.symbol.in_(selected_symbols))
    if to_date:
        adjusted_statement = adjusted_statement.where(AdjustedPrice.trade_date <= to_date)
    adjusted_rows = list(db.scalars(adjusted_statement))
    event_statement = select(MarketEvent).where(
        (MarketEvent.symbol.in_(selected_symbols)) | (MarketEvent.symbol.is_(None))
    )
    if to_date:
        event_statement = event_statement.where(MarketEvent.event_date <= to_date)
    event_rows = list(db.scalars(event_statement))
    news_statement = select(MarketNews).where(
        (MarketNews.symbol.in_(selected_symbols)) | (MarketNews.symbol.is_(None))
    )
    if to_date:
        news_statement = news_statement.where(MarketNews.published_at <= to_date)
    news_rows = list(db.scalars(news_statement))
    result = analyze_ohlcv(
        source_rows,
        from_date=from_date,
        to_date=to_date,
        benchmark_rows=benchmark_rows,
        foreign_rows=foreign_rows,
        broker_rows=broker_rows,
        stock_summary_rows=stock_summary_rows,
        adjusted_rows=adjusted_rows,
        event_rows=event_rows,
        news_rows=news_rows,
    )
    if len(result) > limit:
        return result[-limit:]
    return result


def _broker_summary_result(
    db: Session,
    symbol: str,
    from_date: date | None,
    to_date: date | None,
    days: int,
) -> dict[str, Any]:
    symbol = symbol.upper().strip()
    _validate_range(from_date, to_date)
    statement = select(BrokerSummaryDaily).where(BrokerSummaryDaily.symbol == symbol)
    if from_date:
        statement = statement.where(BrokerSummaryDaily.trade_date >= from_date)
    if to_date:
        statement = statement.where(BrokerSummaryDaily.trade_date <= to_date)
    rows = list(db.scalars(statement.order_by(BrokerSummaryDaily.trade_date.desc())))
    if not rows:
        return {
            "symbol": symbol,
            "trading_dates": [],
            "top_buyers": [],
            "top_sellers": [],
            "data_status": "Belum ada broker summary",
        }
    dates = sorted({row.trade_date for row in rows}, reverse=True)[:days]
    selected = [row for row in rows if row.trade_date in dates]
    grouped: dict[str, dict[str, Any]] = {}
    for row in selected:
        entry = grouped.setdefault(
            row.broker_code,
            {
                "broker_code": row.broker_code,
                "broker_name": row.broker_name,
                "buy_volume": 0,
                "sell_volume": 0,
                "buy_value": Decimal(0),
                "sell_value": Decimal(0),
                "buy_frequency": 0,
                "sell_frequency": 0,
            },
        )
        entry["buy_volume"] += row.buy_volume or 0
        entry["sell_volume"] += row.sell_volume or 0
        entry["buy_value"] += row.buy_value or Decimal(0)
        entry["sell_value"] += row.sell_value or Decimal(0)
        entry["buy_frequency"] += row.buy_frequency or 0
        entry["sell_frequency"] += row.sell_frequency or 0
    output: list[dict[str, Any]] = []
    for entry in grouped.values():
        buy_volume = entry["buy_volume"]
        sell_volume = entry["sell_volume"]
        entry["buy_average"] = entry["buy_value"] / buy_volume if buy_volume else None
        entry["sell_average"] = entry["sell_value"] / sell_volume if sell_volume else None
        entry["net_volume"] = buy_volume - sell_volume
        entry["net_value"] = entry["buy_value"] - entry["sell_value"]
        output.append(
            {
                key: (float(value) if isinstance(value, Decimal) else value)
                for key, value in entry.items()
            }
        )
    return {
        "symbol": symbol,
        "trading_dates": [day.isoformat() for day in sorted(dates)],
        "top_buyers": sorted(output, key=lambda item: item["buy_value"], reverse=True)[:5],
        "top_sellers": sorted(output, key=lambda item: item["sell_value"], reverse=True)[:5],
        "data_status": "ready",
    }


def _market_broker_summary_result(
    db: Session,
    from_date: date | None,
    to_date: date | None,
    days: int,
) -> dict[str, Any]:
    """Aggregate IDX's public whole-market broker totals by broker.

    The public endpoint has no buyer/seller side and no stock code.  The API
    therefore deliberately labels this result as market-wide transaction
    activity rather than per-stock broker flow.
    """

    _validate_range(from_date, to_date)
    statement = select(MarketBrokerSummaryDaily)
    if from_date:
        statement = statement.where(MarketBrokerSummaryDaily.trade_date >= from_date)
    if to_date:
        statement = statement.where(MarketBrokerSummaryDaily.trade_date <= to_date)
    rows = list(
        db.scalars(
            statement.order_by(
                MarketBrokerSummaryDaily.trade_date.desc(),
                MarketBrokerSummaryDaily.value.desc(),
            )
        )
    )
    if not rows:
        return {
            "trading_dates": [],
            "rows": [],
            "top_by_value": [],
            "top_by_volume": [],
            "top_by_frequency": [],
            "data_status": "Belum ada ringkasan broker pasar",
            "scope": "whole_market",
        }

    dates = sorted({row.trade_date for row in rows}, reverse=True)[:days]
    selected = [row for row in rows if row.trade_date in dates]
    grouped: dict[str, dict[str, Any]] = {}
    for row in selected:
        entry = grouped.setdefault(
            row.broker_code,
            {
                "broker_code": row.broker_code,
                "broker_name": row.broker_name,
                "volume": 0,
                "value": Decimal(0),
                "frequency": 0,
            },
        )
        entry["volume"] += row.volume or 0
        entry["value"] += row.value or Decimal(0)
        entry["frequency"] += row.frequency or 0
    output = [
        {
            key: (float(value) if isinstance(value, Decimal) else value)
            for key, value in entry.items()
        }
        for entry in grouped.values()
    ]
    return {
        "trading_dates": [day.isoformat() for day in sorted(dates)],
        "rows": sorted(output, key=lambda item: item["value"], reverse=True),
        "top_by_value": sorted(output, key=lambda item: item["value"], reverse=True)[:5],
        "top_by_volume": sorted(output, key=lambda item: item["volume"], reverse=True)[:5],
        "top_by_frequency": sorted(output, key=lambda item: item["frequency"], reverse=True)[:5],
        "data_status": "ready",
        "scope": "whole_market",
    }


def _jsonable_row(row: Any) -> dict[str, Any]:
    """Serialize one SQLAlchemy row without leaking its internal state."""

    result: dict[str, Any] = {}
    for key, value in vars(row).items():
        if key.startswith("_"):
            continue
        if isinstance(value, Decimal):
            result[key] = float(value)
        elif isinstance(value, (date,)):
            result[key] = value.isoformat()
        elif hasattr(value, "isoformat") and not isinstance(value, str):
            result[key] = value.isoformat()
        else:
            result[key] = value
    if isinstance(row, StockSummaryDaily):
        close = result.get("close")
        listed = result.get("listed_shares")
        tradeable = result.get("tradeable_shares")
        if close is not None and listed:
            result["market_cap"] = float(close) * float(listed)
        else:
            result["market_cap"] = None
        result["free_float_shares"] = tradeable
        result["free_float_percentage"] = (
            float(tradeable) / float(listed) if tradeable is not None and listed else None
        )
        result["free_float_market_cap"] = (
            float(close) * float(tradeable)
            if close is not None and tradeable
            else None
        )
        volume = result.get("volume")
        value = result.get("value")
        result["vwap"] = float(value) / float(volume) if value is not None and volume else None
    if isinstance(row, ForeignFlowDaily):
        buy_volume = result.get("foreign_buy_volume")
        sell_volume = result.get("foreign_sell_volume")
        result["foreign_net_volume"] = (
            float(buy_volume) - float(sell_volume)
            if buy_volume is not None and sell_volume is not None
            else None
        )
    return result


def create_app() -> FastAPI:
    app = FastAPI(title="IDX OHLCV Internal API", version="0.1.0")
    cache = OptionalCache(settings.redis_url, settings.api_cache_ttl)

    @app.on_event("startup")
    def ensure_additive_schema() -> None:
        # Safe additive migration for deployments that already have the
        # original schema. Destructive migrations remain an explicit DBA task.
        Base.metadata.create_all(engine)

    @app.middleware("http")
    async def metrics_middleware(request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        path = request.scope.get("route").path if request.scope.get("route") else request.url.path
        API_REQUESTS.labels(request.method, path, response.status_code).inc()
        API_LATENCY.labels(path).observe(time.perf_counter() - started)
        return response

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard():
        return DASHBOARD_HTML

    @app.get("/health")
    def health(db: Session = Depends(get_db)):
        try:
            db.execute(text("SELECT 1"))
            return {"status": "ok", "database": "ok"}
        except Exception as exc:
            log.error("Database health check failed: %s", exc)
            return JSONResponse(
                status_code=503, content={"status": "error", "database": "unavailable"}
            )

    @app.get("/symbols", response_model=list[SymbolOut])
    def symbols(db: Session = Depends(get_db)):
        key = "symbols"
        cached = cache.get(key)
        if cached is not None:
            return cached
        rows = list(db.scalars(select(Stock).order_by(Stock.symbol)))
        result = [SymbolOut.model_validate(row).model_dump(mode="json") for row in rows]
        cache.set(key, result)
        return result

    @app.get("/ohlcv/{symbol}", response_model=list[OHLCVOut])
    def ohlcv(
        symbol: str,
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        if from_date and to_date and from_date > to_date:
            raise HTTPException(status_code=422, detail="from must not be after to")
        return list(db.scalars(ohlcv_query(symbol, from_date, to_date)))

    @app.get("/ui/api/stock-summary")
    def ui_stock_summary(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        limit: int = Query(5_000, ge=1, le=100_000),
        db: Session = Depends(get_db),
    ):
        selected = _export_symbols(symbols)
        statement = select(StockSummaryDaily)
        if selected:
            statement = statement.where(StockSummaryDaily.symbol.in_(selected))
        if from_date:
            statement = statement.where(StockSummaryDaily.trade_date >= from_date)
        if to_date:
            statement = statement.where(StockSummaryDaily.trade_date <= to_date)
        rows = db.scalars(statement.order_by(StockSummaryDaily.symbol, StockSummaryDaily.trade_date).limit(limit))
        return [_jsonable_row(row) for row in rows]

    @app.get("/ui/api/index-summary")
    def ui_index_summary(
        benchmark: str | None = None,
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        limit: int = Query(5_000, ge=1, le=100_000),
        db: Session = Depends(get_db),
    ):
        statement = select(IndexSummaryDaily)
        if benchmark:
            statement = statement.where(IndexSummaryDaily.benchmark == benchmark.upper())
        if from_date:
            statement = statement.where(IndexSummaryDaily.trade_date >= from_date)
        if to_date:
            statement = statement.where(IndexSummaryDaily.trade_date <= to_date)
        rows = db.scalars(statement.order_by(IndexSummaryDaily.benchmark, IndexSummaryDaily.trade_date).limit(limit))
        return [_jsonable_row(row) for row in rows]

    @app.get("/ui/api/foreign-flow")
    def ui_foreign_flow(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        limit: int = Query(5_000, ge=1, le=100_000),
        db: Session = Depends(get_db),
    ):
        return _feature_rows(db, ForeignFlowDaily, symbols, from_date, to_date, limit)

    @app.get("/ui/api/adjusted-ohlcv")
    def ui_adjusted_ohlcv(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        limit: int = Query(5_000, ge=1, le=100_000),
        db: Session = Depends(get_db),
    ):
        return _feature_rows(db, AdjustedPrice, symbols, from_date, to_date, limit)

    @app.get("/ui/api/data-catalog")
    def ui_data_catalog(db: Session = Depends(get_db)):
        """Show coverage and source readiness for every requested dataset."""

        def count(model: Any) -> int:
            return int(db.scalar(select(func.count()).select_from(model)) or 0)

        return {
            "ohlcv": {"rows": count(OHLCVDaily), "source": "IDX public Stock Summary", "status": "ready"},
            "stock_summary": {"rows": count(StockSummaryDaily), "source": "IDX public Stock Summary", "status": "ready"},
            "index_summary": {"rows": count(IndexSummaryDaily), "source": "IDX public Index Summary", "status": "ready"},
            "foreign_flow": {"rows": count(ForeignFlowDaily), "source": "IDX Stock Summary volume fields", "status": "ready"},
            "market_broker": {"rows": count(MarketBrokerSummaryDaily), "source": "IDX public market-wide broker summary", "status": "market-wide only"},
            "broker_per_stock": {"rows": count(BrokerSummaryDaily), "source": "approved import/provider required", "status": "provider-dependent"},
            "adjusted_prices": {"rows": count(AdjustedPrice), "source": "corporate actions", "status": "rebuild after actions"},
            "order_book": {"rows": count(OrderBookSnapshot), "source": "licensed/live feed or import", "status": "provider-dependent"},
            "intraday": {"rows": count(IntradayTrade), "source": "licensed/live feed or import", "status": "provider-dependent"},
            "fundamentals": {"rows": count(FundamentalQuarterly), "source": "issuer/licensed provider or import", "status": "provider-dependent"},
            "events": {"rows": count(MarketEvent), "source": "IDX corporate actions/import", "status": "ready for imported events"},
            "news": {"rows": count(MarketNews), "source": "news provider/import", "status": "provider-dependent"},
        }

    @app.get("/ui/api/dataset/{dataset}")
    def ui_dataset(
        dataset: str,
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        limit: int = Query(5_000, ge=1, le=100_000),
        db: Session = Depends(get_db),
    ):
        models = {
            "stock-summary": StockSummaryDaily,
            "index-summary": IndexSummaryDaily,
            "foreign-flow": ForeignFlowDaily,
            "broker-summary": BrokerSummaryDaily,
            "order-book": OrderBookSnapshot,
            "intraday-trades": IntradayTrade,
            "fundamentals": FundamentalQuarterly,
            "events": MarketEvent,
            "news": MarketNews,
            "adjusted-ohlcv": AdjustedPrice,
        }
        model = models.get(dataset.lower())
        if model is None:
            raise HTTPException(status_code=404, detail="dataset tidak dikenal")
        return _feature_rows(db, model, symbols, from_date, to_date, limit)

    @app.get("/ui/api/symbol-features")
    def ui_symbol_features(
        symbol: str,
        trade_date: date | None = Query(None, alias="date"),
        db: Session = Depends(get_db),
    ):
        symbol = symbol.upper().strip()
        if not symbol:
            raise HTTPException(status_code=422, detail="symbol wajib diisi")
        order_statement = select(OrderBookSnapshot).where(OrderBookSnapshot.symbol == symbol)
        trade_statement = select(IntradayTrade).where(IntradayTrade.symbol == symbol)
        if trade_date:
            start_at = datetime.combine(trade_date, datetime.min.time())
            end_at = start_at + timedelta(days=1)
            order_statement = order_statement.where(
                OrderBookSnapshot.captured_at >= start_at,
                OrderBookSnapshot.captured_at < end_at,
            )
            trade_statement = trade_statement.where(
                IntradayTrade.traded_at >= start_at,
                IntradayTrade.traded_at < end_at,
            )
        order_rows = list(db.scalars(order_statement.order_by(OrderBookSnapshot.captured_at.desc()).limit(200)))
        trade_rows = list(db.scalars(trade_statement.order_by(IntradayTrade.traded_at.desc()).limit(5_000)))
        fundamental_rows = list(db.scalars(select(FundamentalQuarterly).where(FundamentalQuarterly.symbol == symbol).order_by(FundamentalQuarterly.fiscal_year, FundamentalQuarterly.fiscal_quarter)))
        event_statement = select(MarketEvent).where(
            (MarketEvent.symbol == symbol) | (MarketEvent.symbol.is_(None))
        )
        if trade_date:
            event_statement = event_statement.where(MarketEvent.event_date == trade_date)
        event_rows = list(db.scalars(event_statement.order_by(MarketEvent.event_date.desc()).limit(200)))
        return {"symbol": symbol, "date": trade_date.isoformat() if trade_date else None, "order_book": summarize_order_book(order_rows), "intraday": summarize_intraday(trade_rows), "fundamentals": summarize_fundamentals(fundamental_rows), "events": summarize_events(event_rows)}

    @app.get("/export", include_in_schema=False)
    def export_page():
        return RedirectResponse(url="/", status_code=302)

    def filtered_export_rows(
        db: Session,
        symbols: str | None,
        from_date: date | None,
        to_date: date | None,
    ) -> tuple[list[OHLCVDaily], list[str] | None]:
        if from_date and to_date and from_date > to_date:
            raise HTTPException(status_code=422, detail="from must not be after to")
        selected_symbols = _export_symbols(symbols)
        statement = select(OHLCVDaily)
        if selected_symbols:
            statement = statement.where(OHLCVDaily.symbol.in_(selected_symbols))
        if from_date:
            statement = statement.where(OHLCVDaily.trade_date >= from_date)
        if to_date:
            statement = statement.where(OHLCVDaily.trade_date <= to_date)
        statement = statement.order_by(OHLCVDaily.symbol, OHLCVDaily.trade_date).limit(
            MAX_EXPORT_ROWS + 1
        )
        rows = list(db.scalars(statement))
        if not rows:
            raise HTTPException(status_code=404, detail="no OHLCV rows matched the export filters")
        if len(rows) > MAX_EXPORT_ROWS:
            raise HTTPException(
                status_code=413,
                detail=f"export exceeds {MAX_EXPORT_ROWS:,} rows; narrow the symbols or dates",
            )
        return rows, selected_symbols

    @app.get("/export/ohlcv.csv", response_class=Response)
    def export_ohlcv_csv(
        symbols: str | None = Query(None, description="Comma-separated IDX symbols"),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        rows, selected_symbols = filtered_export_rows(db, symbols, from_date, to_date)
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "symbol",
                "trade_date",
                "currency",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "source",
                "ingested_at",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.symbol,
                    row.trade_date.isoformat(),
                    "IDR",
                    row.open,
                    row.high,
                    row.low,
                    row.close,
                    row.volume,
                    row.source,
                    row.ingested_at.isoformat() if row.ingested_at else "",
                ]
            )
        filename = _export_filename(selected_symbols, from_date, to_date, "csv")
        return Response(
            content="\ufeff" + output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/export/ohlcv.xlsx", response_class=Response)
    def export_ohlcv_excel(
        symbols: str | None = Query(None, description="Comma-separated IDX symbols"),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        rows, selected_symbols = filtered_export_rows(db, symbols, from_date, to_date)
        workbook = build_ohlcv_workbook(rows)
        filename = _export_filename(selected_symbols, from_date, to_date, "xlsx")
        return Response(
            content=workbook,
            media_type=EXCEL_MIME_TYPE,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/export/analysis.csv", response_class=Response)
    def export_analysis_csv(
        symbols: str | None = Query(None, description="Comma-separated IDX symbols"),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        rows = _analysis_rows(db, symbols, from_date, to_date, MAX_EXPORT_ROWS)
        output = StringIO(newline="")
        writer = csv.writer(output)
        fields = [
            "symbol",
            "trade_date",
            "close",
            "ma5",
            "ma10",
            "ma20",
            "ma50",
            "ema5",
            "ema10",
            "ema20",
            "ema50",
            "rsi14",
            "atr14",
            "return5",
            "return10",
            "return20",
            "volume_ratio20",
            "volatility20",
            "mean_reversion_z20",
            "mean_reversion_signal",
            "mean_reversion_score",
            "ensemble_score",
            "market_regime",
            "benchmark_observation_count",
            "benchmark_required_observations",
            "benchmark_status",
            "breakout_20",
            "relative_strength_rank",
            "trend_score",
            "simons_score",
            "simons_label",
            "p_model",
            "p_market",
            "p_final",
            "edge",
            "benchmark_return20",
            "excess_return20",
            "beta20",
            "correlation20",
            "benchmark_volatility20",
            "residual_momentum20",
            "trading_value",
            "frequency",
            "vwap",
            "market_cap",
            "free_float_shares",
            "free_float_percentage",
            "free_float_market_cap",
            "tradeable_shares",
            "turnover_ratio",
            "broker_concentration",
            "broker_persistence",
            "foreign_persistence",
            "foreign_net_value",
            "broker_net_value",
            "flow_confirmation",
            "event_count",
            "event_risk",
            "sentiment_score",
            "stop_price",
            "take_profit_price",
            "entry_signal",
            "price_source",
            "probability_status",
            "data_status",
            "model_version",
        ]
        writer.writerow(fields)
        for row in rows:
            writer.writerow([row.get(field, "") if row.get(field) is not None else "" for field in fields])
        selected_symbols = _export_symbols(symbols)
        filename = _export_filename(selected_symbols, from_date, to_date, "csv").replace(
            "idx_ohlcv_", "idx_analysis_"
        )
        return Response(
            content="\ufeff" + output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/export/analysis.xlsx", response_class=Response)
    def export_analysis_excel(
        symbols: str | None = Query(None, description="Comma-separated IDX symbols"),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        rows = _analysis_rows(db, symbols, from_date, to_date, MAX_EXPORT_ROWS)
        workbook = build_analysis_workbook(rows)
        selected_symbols = _export_symbols(symbols)
        filename = _export_filename(selected_symbols, from_date, to_date, "xlsx").replace(
            "idx_ohlcv_", "idx_analysis_"
        )
        return Response(
            content=workbook,
            media_type=EXCEL_MIME_TYPE,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def broker_export_rows(
        db: Session,
        symbol: str,
        from_date: date | None,
        to_date: date | None,
        days: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        summary = _broker_summary_result(db, symbol, from_date, to_date, days)
        rows: list[dict[str, Any]] = []
        for position, key in (("buyer", "top_buyers"), ("seller", "top_sellers")):
            for rank, row in enumerate(summary[key], start=1):
                rows.append({"position": position, "rank": rank, **row})
        return summary, rows

    @app.get("/export/broker-summary.csv", response_class=Response)
    def export_broker_csv(
        symbol: str,
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        days: int = Query(1, ge=1, le=60),
        db: Session = Depends(get_db),
    ):
        summary, rows = broker_export_rows(db, symbol, from_date, to_date, days)
        if not rows:
            raise HTTPException(status_code=404, detail="belum ada broker summary untuk diekspor")
        fields = [
            "position",
            "rank",
            "broker_code",
            "broker_name",
            "buy_volume",
            "buy_value",
            "buy_average",
            "sell_volume",
            "sell_value",
            "sell_average",
            "net_volume",
            "net_value",
            "buy_frequency",
            "sell_frequency",
        ]
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(fields)
        writer.writerow([])
        for row in rows:
            writer.writerow([row.get(field, "") if row.get(field) is not None else "" for field in fields])
        filename = f"idx_broker_summary_{summary['symbol']}_{days}d.csv"
        return Response(
            content="\ufeff" + output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/export/broker-summary.xlsx", response_class=Response)
    def export_broker_excel(
        symbol: str,
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        days: int = Query(1, ge=1, le=60),
        db: Session = Depends(get_db),
    ):
        summary, rows = broker_export_rows(db, symbol, from_date, to_date, days)
        if not rows:
            raise HTTPException(status_code=404, detail="belum ada broker summary untuk diekspor")
        filename = f"idx_broker_summary_{summary['symbol']}_{days}d.xlsx"
        return Response(
            content=build_broker_workbook(summary, rows),
            media_type=EXCEL_MIME_TYPE,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/export/market-broker-summary.csv", response_class=Response)
    def export_market_broker_csv(
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        days: int = Query(1, ge=1, le=60),
        db: Session = Depends(get_db),
    ):
        summary = _market_broker_summary_result(db, from_date, to_date, days)
        rows = summary["rows"]
        if not rows:
            raise HTTPException(
                status_code=404,
                detail="belum ada ringkasan broker seluruh pasar untuk diekspor",
            )
        fields = ["rank", "broker_code", "broker_name", "volume", "value", "frequency"]
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(fields)
        for rank, row in enumerate(rows, start=1):
            writer.writerow(
                [
                    rank,
                    *(
                        row.get(field) if row.get(field) is not None else ""
                        for field in fields[1:]
                    ),
                ]
            )
        return Response(
            content="\ufeff" + output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="idx_market_broker_summary_{days}d.csv"'
                )
            },
        )

    @app.get("/export/market-broker-summary.xlsx", response_class=Response)
    def export_market_broker_excel(
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        days: int = Query(1, ge=1, le=60),
        db: Session = Depends(get_db),
    ):
        summary = _market_broker_summary_result(db, from_date, to_date, days)
        if not summary["rows"]:
            raise HTTPException(
                status_code=404,
                detail="belum ada ringkasan broker seluruh pasar untuk diekspor",
            )
        return Response(
            content=build_market_broker_workbook(summary),
            media_type=EXCEL_MIME_TYPE,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="idx_market_broker_summary_{days}d.xlsx"'
                )
            },
        )

    def _feature_rows(db: Session, model: Any, symbols: str | None, from_date: date | None, to_date: date | None, limit: int):
        selected = _export_symbols(symbols)
        statement = select(model)
        if selected and hasattr(model, "symbol"):
            statement = statement.where(model.symbol.in_(selected))
        date_name = next(
            (
                name
                for name in ("trade_date", "event_date", "report_date", "captured_at", "traded_at", "published_at")
                if hasattr(model, name)
            ),
            None,
        )
        date_column = getattr(model, date_name) if date_name else None
        is_datetime = date_name in {"captured_at", "traded_at", "published_at"}
        if from_date:
            if date_column is not None:
                start_value = datetime.combine(from_date, datetime.min.time()) if is_datetime else from_date
                statement = statement.where(date_column >= start_value)
        if to_date:
            if date_column is not None:
                end_value = datetime.combine(to_date, datetime.max.time()) if is_datetime else to_date
                statement = statement.where(date_column <= end_value)
        return [_jsonable_row(row) for row in db.scalars(statement.limit(limit))]

    @app.get("/export/feature/{dataset}.csv", response_class=Response)
    def export_feature_csv(
        dataset: str,
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        models = {
            "stock-summary": StockSummaryDaily,
            "index-summary": IndexSummaryDaily,
            "foreign-flow": ForeignFlowDaily,
            "broker-summary": BrokerSummaryDaily,
            "order-book": OrderBookSnapshot,
            "intraday-trades": IntradayTrade,
            "fundamentals": FundamentalQuarterly,
            "events": MarketEvent,
            "news": MarketNews,
            "adjusted-ohlcv": AdjustedPrice,
        }
        model = models.get(dataset.lower())
        if model is None:
            raise HTTPException(status_code=404, detail="dataset export tidak dikenal")
        rows = _feature_rows(db, model, symbols, from_date, to_date, MAX_EXPORT_ROWS)
        if not rows:
            raise HTTPException(status_code=404, detail="belum ada data untuk dataset dan filter tersebut")
        fields = sorted({key for row in rows for key in row if key != "raw_payload"})
        return _feature_export_csv(rows, fields, f"idx_{dataset}.csv")

    @app.get("/export/feature/{dataset}.xlsx", response_class=Response)
    def export_feature_excel(
        dataset: str,
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        models = {
            "stock-summary": StockSummaryDaily,
            "index-summary": IndexSummaryDaily,
            "foreign-flow": ForeignFlowDaily,
            "broker-summary": BrokerSummaryDaily,
            "order-book": OrderBookSnapshot,
            "intraday-trades": IntradayTrade,
            "fundamentals": FundamentalQuarterly,
            "events": MarketEvent,
            "news": MarketNews,
            "adjusted-ohlcv": AdjustedPrice,
        }
        model = models.get(dataset.lower())
        if model is None:
            raise HTTPException(status_code=404, detail="dataset export tidak dikenal")
        rows = _feature_rows(db, model, symbols, from_date, to_date, MAX_EXPORT_ROWS)
        if not rows:
            raise HTTPException(status_code=404, detail="belum ada data untuk dataset dan filter tersebut")
        fields = sorted({key for row in rows for key in row if key != "raw_payload"})
        columns = []
        for key in fields:
            kind = "text"
            if key.endswith("_date") or key in {"trade_date", "event_date"}:
                kind = "date"
            elif any(token in key for token in ("value", "price", "revenue", "ebitda", "income", "cash", "debt", "capex", "average", "factor")):
                kind = "currency"
            elif any(token in key for token in ("volume", "frequency", "shares", "level", "year", "quarter", "sequence")):
                kind = "number"
            columns.append((key.replace("_", " ").title(), key, kind))
        return Response(content=build_table_workbook(f"IDX {dataset}", columns, rows, sheet_name="Data"), media_type=EXCEL_MIME_TYPE, headers={"Content-Disposition": f'attachment; filename="idx_{dataset}.xlsx"'})

    @app.get("/export/stock-summary.csv", response_class=Response)
    def export_stock_summary_csv(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        rows = _feature_rows(db, StockSummaryDaily, symbols, from_date, to_date, MAX_EXPORT_ROWS)
        fields = [
            "symbol", "trade_date", "company_name", "previous", "open_price", "first_trade", "high", "low", "close", "change",
            "volume", "value", "frequency", "foreign_buy_volume", "foreign_sell_volume", "non_regular_volume", "non_regular_value",
            "non_regular_frequency", "listed_shares", "tradeable_shares", "weight_for_index", "index_individual",
            "market_cap", "free_float_shares", "free_float_percentage", "free_float_market_cap", "vwap", "source",
        ]
        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return Response(content="\ufeff" + output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="idx_stock_summary.csv"'})

    @app.get("/export/stock-summary.xlsx", response_class=Response)
    def export_stock_summary_excel(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        rows = _feature_rows(db, StockSummaryDaily, symbols, from_date, to_date, MAX_EXPORT_ROWS)
        fields = [
            ("Symbol", "symbol", "text"), ("Tanggal", "trade_date", "date"), ("Nama Emiten", "company_name", "text"),
            ("Previous", "previous", "currency"), ("Open", "open_price", "currency"), ("First Trade", "first_trade", "currency"),
            ("High", "high", "currency"), ("Low", "low", "currency"), ("Close", "close", "currency"), ("Change", "change", "number"),
            ("Volume", "volume", "number"), ("Value (Rp)", "value", "currency"), ("Frequency", "frequency", "number"),
            ("Foreign Buy Vol", "foreign_buy_volume", "number"), ("Foreign Sell Vol", "foreign_sell_volume", "number"),
            ("Listed Shares", "listed_shares", "number"), ("Tradeable Shares", "tradeable_shares", "number"),
            ("Market Cap (Rp)", "market_cap", "currency"), ("Free Float Shares", "free_float_shares", "number"),
            ("Free Float %", "free_float_percentage", "percent"), ("Free Float Market Cap (Rp)", "free_float_market_cap", "currency"),
            ("VWAP", "vwap", "currency"),
        ]
        return Response(content=build_table_workbook("IDX Stock Summary", fields, rows, sheet_name="Stock Summary"), media_type=EXCEL_MIME_TYPE, headers={"Content-Disposition": 'attachment; filename="idx_stock_summary.xlsx"'})

    @app.get("/export/index-summary.csv", response_class=Response)
    def export_index_summary_csv(
        benchmark: str | None = None,
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        rows = _feature_rows(db, IndexSummaryDaily, None, from_date, to_date, MAX_EXPORT_ROWS)
        if benchmark:
            rows = [row for row in rows if row.get("benchmark") == benchmark.upper()]
        fields = ["benchmark", "trade_date", "previous", "highest", "lowest", "close", "change", "number_of_stock", "volume", "value", "frequency", "source"]
        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return Response(content="\ufeff" + output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="idx_index_summary.csv"'})

    @app.get("/export/index-summary.xlsx", response_class=Response)
    def export_index_summary_excel(
        benchmark: str | None = None,
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        rows = _feature_rows(db, IndexSummaryDaily, None, from_date, to_date, MAX_EXPORT_ROWS)
        if benchmark:
            rows = [row for row in rows if row.get("benchmark") == benchmark.upper()]
        fields = [("Index", "benchmark", "text"), ("Tanggal", "trade_date", "date"), ("Previous", "previous", "number"), ("Highest", "highest", "number"), ("Lowest", "lowest", "number"), ("Close", "close", "number"), ("Change", "change", "number"), ("Stocks", "number_of_stock", "number"), ("Volume", "volume", "number"), ("Value (Rp)", "value", "currency"), ("Frequency", "frequency", "number")]
        return Response(content=build_table_workbook("IDX Index Summary", fields, rows, sheet_name="Index Summary"), media_type=EXCEL_MIME_TYPE, headers={"Content-Disposition": 'attachment; filename="idx_index_summary.xlsx"'})

    def _feature_export_csv(rows: list[dict[str, Any]], fields: list[str], filename: str) -> Response:
        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return Response(content="\ufeff" + output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.get("/export/foreign-flow.csv", response_class=Response)
    def export_foreign_flow_csv(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        fields = ["symbol", "trade_date", "foreign_buy_volume", "foreign_sell_volume", "foreign_net_volume", "foreign_buy_value", "foreign_sell_value", "foreign_net_value", "foreign_average_buy", "foreign_average_sell", "source"]
        return _feature_export_csv(_feature_rows(db, ForeignFlowDaily, symbols, from_date, to_date, MAX_EXPORT_ROWS), fields, "idx_foreign_flow.csv")

    @app.get("/export/adjusted-ohlcv.csv", response_class=Response)
    def export_adjusted_csv(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        fields = ["symbol", "trade_date", "adjustment_factor", "adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close", "adjusted_volume", "calculated_at"]
        return _feature_export_csv(_feature_rows(db, AdjustedPrice, symbols, from_date, to_date, MAX_EXPORT_ROWS), fields, "idx_adjusted_ohlcv.csv")

    @app.get("/export/foreign-flow.xlsx", response_class=Response)
    def export_foreign_flow_excel(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        rows = _feature_rows(db, ForeignFlowDaily, symbols, from_date, to_date, MAX_EXPORT_ROWS)
        columns = [("Symbol", "symbol", "text"), ("Tanggal", "trade_date", "date"), ("Foreign Buy Vol", "foreign_buy_volume", "number"), ("Foreign Sell Vol", "foreign_sell_volume", "number"), ("Foreign Net Vol", "foreign_net_volume", "number"), ("Foreign Buy Value", "foreign_buy_value", "currency"), ("Foreign Sell Value", "foreign_sell_value", "currency"), ("Net Value", "foreign_net_value", "currency"), ("Avg Buy", "foreign_average_buy", "currency"), ("Avg Sell", "foreign_average_sell", "currency")]
        return Response(content=build_table_workbook("IDX Foreign Flow", columns, rows, sheet_name="Foreign Flow"), media_type=EXCEL_MIME_TYPE, headers={"Content-Disposition": 'attachment; filename="idx_foreign_flow.xlsx"'})

    @app.get("/export/adjusted-ohlcv.xlsx", response_class=Response)
    def export_adjusted_excel(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        db: Session = Depends(get_db),
    ):
        rows = _feature_rows(db, AdjustedPrice, symbols, from_date, to_date, MAX_EXPORT_ROWS)
        columns = [("Symbol", "symbol", "text"), ("Tanggal", "trade_date", "date"), ("Adjustment Factor", "adjustment_factor", "number"), ("Adjusted Open", "adjusted_open", "currency"), ("Adjusted High", "adjusted_high", "currency"), ("Adjusted Low", "adjusted_low", "currency"), ("Adjusted Close", "adjusted_close", "currency"), ("Adjusted Volume", "adjusted_volume", "number"), ("Calculated At", "calculated_at", "text")]
        return Response(content=build_table_workbook("IDX Adjusted OHLCV", columns, rows, sheet_name="Adjusted OHLCV"), media_type=EXCEL_MIME_TYPE, headers={"Content-Disposition": 'attachment; filename="idx_adjusted_ohlcv.xlsx"'})

    @app.get("/latest", response_model=list[OHLCVOut])
    def latest(db: Session = Depends(get_db)):
        cached = cache.get("latest")
        if cached is not None:
            return cached
        latest_date = db.scalar(select(func.max(OHLCVDaily.trade_date)))
        if latest_date is None:
            return []
        rows = list(
            db.scalars(
                select(OHLCVDaily)
                .where(OHLCVDaily.trade_date == latest_date)
                .order_by(desc(OHLCVDaily.volume))
            )
        )
        result = [OHLCVOut.model_validate(row).model_dump(mode="json") for row in rows]
        cache.set("latest", result)
        return result

    @app.get("/ui/api/overview")
    def ui_overview(db: Session = Depends(get_db)):
        total_rows, total_symbols, earliest_date, latest_date = db.execute(
            select(
                func.count(OHLCVDaily.symbol),
                func.count(func.distinct(OHLCVDaily.symbol)),
                func.min(OHLCVDaily.trade_date),
                func.max(OHLCVDaily.trade_date),
            )
        ).one()
        last_run = db.scalar(select(ETLRun).order_by(desc(ETLRun.started_at)).limit(1))
        return {
            "total_rows": total_rows,
            "total_symbols": total_symbols,
            "earliest_date": earliest_date,
            "latest_date": latest_date,
            "last_run": (
                {
                    "job_name": last_run.job_name,
                    "status": last_run.status,
                    "rows_loaded": last_run.rows_loaded,
                    "rows_rejected": last_run.rows_rejected,
                }
                if last_run
                else None
            ),
        }

    @app.get("/ui/api/ohlcv", response_model=list[OHLCVWithIndicatorsOut])
    def ui_ohlcv(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        limit: int = Query(500, ge=1, le=5_000),
        db: Session = Depends(get_db),
    ):
        if from_date and to_date and from_date > to_date:
            raise HTTPException(status_code=422, detail="Tanggal mulai tidak boleh setelah akhir")
        selected_symbols = _export_symbols(symbols)
        statement = select(OHLCVDaily)
        if selected_symbols:
            statement = statement.where(OHLCVDaily.symbol.in_(selected_symbols))
        if from_date:
            statement = statement.where(OHLCVDaily.trade_date >= from_date)
        if to_date:
            statement = statement.where(OHLCVDaily.trade_date <= to_date)
        rows = list(
            db.scalars(
                statement.order_by(OHLCVDaily.symbol, OHLCVDaily.trade_date).limit(limit)
            )
        )
        result = [OHLCVOut.model_validate(row).model_dump(mode="json") for row in rows]
        # The primary table now exposes the same trading-session moving
        # averages as the analysis panel.  We only calculate them when an
        # explicit symbol filter is present; an unfiltered all-market table
        # should remain a cheap OHLCV query.
        if selected_symbols and rows:
            analysis = _analysis_rows(db, symbols, from_date, to_date, max(limit, 20_000))
            indicators = {
                (item["symbol"], item["trade_date"]): {
                    "ma5": item["ma5"],
                    "ma10": item["ma10"],
                    "ma20": item["ma20"],
                    "ma50": item["ma50"],
                    "ema5": item["ema5"],
                    "ema10": item["ema10"],
                    "ema20": item["ema20"],
                    "ema50": item["ema50"],
                    "rsi14": item["rsi14"],
                    "atr14": item["atr14"],
                    "market_regime": item["market_regime"],
                    "ensemble_score": item["ensemble_score"],
                    "entry_signal": item["entry_signal"],
                    "price_source": item["price_source"],
                }
                for item in analysis
            }
            for item in result:
                item.update(indicators.get((item["symbol"], item["trade_date"]), {}))
        return result

    @app.get("/ui/api/analysis")
    def ui_analysis(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        limit: int = Query(5_000, ge=1, le=20_000),
        db: Session = Depends(get_db),
    ):
        return _analysis_rows(db, symbols, from_date, to_date, limit)

    @app.get("/ui/api/backtest")
    def ui_backtest(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        horizon: int = Query(5, ge=1, le=50),
        score_threshold: float = Query(65, ge=0, le=100),
        probability_threshold: float = Query(0.55, ge=0, le=1),
        db: Session = Depends(get_db),
    ):
        selected = _export_symbols(symbols)
        if not selected:
            raise HTTPException(status_code=422, detail="Isi minimal satu simbol untuk backtest")
        statement = select(OHLCVDaily).where(OHLCVDaily.symbol.in_(selected))
        if from_date:
            # Include the warm-up history before the visible test range.
            statement = statement.where(OHLCVDaily.trade_date <= (to_date or date.today()))
        elif to_date:
            statement = statement.where(OHLCVDaily.trade_date <= to_date)
        source_rows = list(db.scalars(statement.order_by(OHLCVDaily.symbol, OHLCVDaily.trade_date)))
        benchmark_rows = list(db.scalars(select(BenchmarkDaily).where(BenchmarkDaily.benchmark == "IHSG").order_by(BenchmarkDaily.trade_date)))
        foreign_rows = list(db.scalars(select(ForeignFlowDaily).where(ForeignFlowDaily.symbol.in_(selected))))
        broker_rows = list(db.scalars(select(BrokerSummaryDaily).where(BrokerSummaryDaily.symbol.in_(selected))))
        summary_rows = list(db.scalars(select(StockSummaryDaily).where(StockSummaryDaily.symbol.in_(selected))))
        adjusted_rows = list(db.scalars(select(AdjustedPrice).where(AdjustedPrice.symbol.in_(selected))))
        event_rows = list(db.scalars(select(MarketEvent).where((MarketEvent.symbol.in_(selected)) | (MarketEvent.symbol.is_(None)))))
        news_rows = list(db.scalars(select(MarketNews).where((MarketNews.symbol.in_(selected)) | (MarketNews.symbol.is_(None)))))
        result = walk_forward_backtest(
            source_rows,
            benchmark_rows=benchmark_rows,
            foreign_rows=foreign_rows,
            broker_rows=broker_rows,
            stock_summary_rows=summary_rows,
            adjusted_rows=adjusted_rows,
            event_rows=event_rows,
            news_rows=news_rows,
            horizon=horizon,
            score_threshold=score_threshold,
            probability_threshold=probability_threshold,
        )
        if from_date:
            result["rows"] = [row for row in result["rows"] if date.fromisoformat(row["signal_date"]) >= from_date]
        if to_date:
            result["rows"] = [row for row in result["rows"] if date.fromisoformat(row["signal_date"]) <= to_date]
        result.update(summarize_backtest_outcomes(result["rows"]))
        result["status"] = "ready" if result["rows"] else "insufficient-history"
        return result

    @app.get("/ui/api/position-size")
    def ui_position_size(
        capital: float = Query(..., gt=0),
        risk_fraction: float = Query(0.01, gt=0, le=1),
        atr: float | None = Query(None, gt=0),
        price: float | None = Query(None, gt=0),
        stop_multiple: float = Query(2.0, gt=0, le=10),
    ):
        return volatility_position_size(capital=capital, risk_fraction=risk_fraction, atr=atr, price=price, stop_multiple=stop_multiple)

    @app.get("/ui/api/broker-summary")
    def ui_broker_summary(
        symbol: str,
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        days: int = Query(1, ge=1, le=60),
        db: Session = Depends(get_db),
    ):
        return _broker_summary_result(db, symbol, from_date, to_date, days)

    @app.get("/ui/api/market-broker-summary")
    def ui_market_broker_summary(
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        days: int = Query(1, ge=1, le=60),
        db: Session = Depends(get_db),
    ):
        return _market_broker_summary_result(db, from_date, to_date, days)

    @app.post("/ui/api/import/{dataset}")
    def import_dataset(
        dataset: str,
        request: DatasetImportRequest,
        db: Session = Depends(get_db),
    ):
        try:
            rows, errors = parse_dataset(dataset, request.content, request.source[:50] or "import")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        loaded = _persist_import_rows(db, dataset, rows)
        db.commit()
        return {"dataset": dataset, "rows_loaded": loaded, "rows_with_warnings": errors}

    def _persist_import_rows(db: Session, dataset: str, rows: list[dict[str, Any]]) -> int:
        """Persist validated CSV/XLSX rows through one code path."""

        dataset = dataset.lower().strip()
        if dataset == "ohlcv":
            ensure_stock_symbols(db, (row["symbol"] for row in rows))
            return upsert_ohlcv(db, rows)
        elif dataset == "stock-summary":
            ensure_stock_symbols(db, (row["symbol"] for row in rows))
            return upsert_stock_summary(db, rows)
        elif dataset == "benchmark":
            return upsert_benchmarks(db, rows)
        elif dataset == "index-summary":
            return upsert_index_summary(db, rows)
        elif dataset == "foreign-flow":
            ensure_stock_symbols(db, (row["symbol"] for row in rows))
            return upsert_foreign_flow(db, rows)
        elif dataset == "broker-summary":
            ensure_stock_symbols(db, (row["symbol"] for row in rows))
            return upsert_broker_summary(db, rows)
        elif dataset == "order-book":
            return upsert_order_book(db, rows)
        elif dataset == "intraday-trades":
            return upsert_intraday_trades(db, rows)
        elif dataset == "fundamentals":
            return upsert_fundamentals(db, rows)
        elif dataset == "events":
            return upsert_market_events(db, rows)
        elif dataset == "news":
            return upsert_market_news(db, rows)
        else:
            raise HTTPException(status_code=422, detail="dataset tidak dikenal")

    @app.post("/ui/api/import-upload/{dataset}")
    async def import_dataset_upload(
        dataset: str,
        upload: UploadFile = File(...),
        db: Session = Depends(get_db),
    ):
        """Accept a CSV or XLSX file from the dashboard import control."""

        content = await upload.read()
        if len(content) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File impor maksimal 25 MB")
        try:
            rows, errors = parse_uploaded_file(
                dataset,
                upload.filename or "upload.csv",
                content,
                (upload.filename or "upload")[:50],
            )
            loaded = _persist_import_rows(db, dataset, rows)
            db.commit()
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"dataset": dataset, "rows_loaded": loaded, "rows_with_warnings": errors}

    @app.get("/ui/api/etl-runs", response_model=list[ETLRunOut])
    def ui_etl_runs(limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
        return list(db.scalars(select(ETLRun).order_by(desc(ETLRun.started_at)).limit(limit)))

    def start_ui_job(name: str, command: list[str]):
        try:
            return job_manager.start(name, command)
        except JobAlreadyRunningError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Job lain masih berjalan: {exc}",
            ) from exc
        except JobCooldownError as exc:
            raise HTTPException(
                status_code=429,
                detail=f"Tunggu {exc.retry_after} detik sebelum memulai proses berikutnya",
                headers={"Retry-After": str(exc.retry_after)},
            ) from exc

    @app.get("/ui/api/jobs/current")
    def current_ui_job():
        return job_manager.current()

    @app.post("/ui/api/jobs/reset")
    def reset_ui_job():
        try:
            job_manager.reset()
        except JobAlreadyRunningError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Proses masih berjalan dan belum dapat direset: {exc}",
            ) from exc
        return {"status": "reset"}

    @app.post("/ui/api/jobs/sync-symbols", status_code=202)
    def start_sync_symbols():
        return start_ui_job("Scraping daftar saham", ["idx-platform", "sync-symbols"])

    @app.post("/ui/api/jobs/daily", status_code=202)
    def start_daily_update(request: DailyJobRequest):
        end_date = request.end or date.today()
        return start_ui_job(
            "Scraping data terbaru",
            ["idx-platform", "daily", "--end", end_date.isoformat()],
        )

    @app.post("/ui/api/jobs/market-broker-summary", status_code=202)
    def start_market_broker_summary(request: DateRangeJobRequest):
        if request.start > request.end:
            raise HTTPException(status_code=422, detail="Tanggal mulai tidak boleh setelah akhir")
        return start_ui_job(
            "Scraping ringkasan broker seluruh pasar",
            [
                "idx-platform",
                "market-broker-summary",
                "--start",
                request.start.isoformat(),
                "--end",
                request.end.isoformat(),
            ],
        )

    @app.post("/ui/api/jobs/index-summary", status_code=202)
    def start_index_summary(request: DateRangeJobRequest):
        if request.start > request.end:
            raise HTTPException(status_code=422, detail="Tanggal mulai tidak boleh setelah akhir")
        # Fetch enough pre-period IHSG history for the 20-session benchmark
        # return used by regime and the combined probability model.
        benchmark_start = benchmark_backfill_start(request.start)
        return start_ui_job(
            "Scraping IHSG dan indeks IDX",
            [
                "idx-platform",
                "index-summary",
                "--start",
                benchmark_start.isoformat(),
                "--end",
                request.end.isoformat(),
            ],
        )

    @app.post("/ui/api/jobs/corporate-actions", status_code=202)
    def start_corporate_actions(request: SymbolsDateRangeJobRequest):
        if request.start > request.end:
            raise HTTPException(status_code=422, detail="Tanggal mulai tidak boleh setelah akhir")
        selected_symbols = _export_symbols(request.symbols)
        if not selected_symbols:
            raise HTTPException(status_code=422, detail="Isi minimal satu simbol")
        return start_ui_job(
            "Scraping corporate action",
            ["idx-platform", "corporate-actions", "--symbols", *selected_symbols, "--start", request.start.isoformat(), "--end", request.end.isoformat()],
        )

    @app.post("/ui/api/jobs/adjust", status_code=202)
    def start_adjusted_prices(request: SymbolsJobRequest):
        selected_symbols = _export_symbols(request.symbols)
        if not selected_symbols:
            raise HTTPException(status_code=422, detail="Isi minimal satu simbol")
        return start_ui_job("Bangun harga adjusted", ["idx-platform", "adjust", *selected_symbols])

    @app.post("/ui/api/jobs/backfill", status_code=202)
    def start_backfill(request: BackfillJobRequest):
        if request.start > request.end:
            raise HTTPException(status_code=422, detail="Tanggal mulai tidak boleh setelah akhir")
        selected_symbols = _export_symbols(request.symbols)
        if not selected_symbols:
            raise HTTPException(status_code=422, detail="Isi minimal satu simbol")
        if len(selected_symbols) > 20:
            raise HTTPException(
                status_code=422,
                detail="Maksimum 20 kode saham per pengambilan data historis",
            )
        return start_ui_job(
            "Scraping data historis",
            [
                "idx-platform",
                "backfill",
                "--symbols",
                *selected_symbols,
                "--start",
                request.start.isoformat(),
                "--end",
                request.end.isoformat(),
            ],
        )

    @app.get("/etl-runs", response_model=list[ETLRunOut])
    def etl_runs(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
        return list(db.scalars(select(ETLRun).order_by(desc(ETLRun.started_at)).limit(limit)))

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
