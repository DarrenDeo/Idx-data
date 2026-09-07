from __future__ import annotations

import csv
import logging
import re
import time
from datetime import date
from decimal import Decimal
from io import StringIO
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.api.cache import OptionalCache
from app.api.dashboard import DASHBOARD_HTML
from app.api.jobs import JobAlreadyRunningError, JobCooldownError, job_manager
from app.analytics import analyze_ohlcv
from app.config import settings
from app.data_import import parse_dataset
from app.database.connection import get_db
from app.database.models import (
    BenchmarkDaily,
    BrokerSummaryDaily,
    ETLRun,
    ForeignFlowDaily,
    OHLCVDaily,
    Stock,
)
from app.database.queries import (
    ohlcv_query,
    upsert_benchmarks,
    upsert_broker_summary,
    upsert_foreign_flow,
)
from app.exporting.excel import (
    EXCEL_MIME_TYPE,
    build_analysis_workbook,
    build_broker_workbook,
    build_ohlcv_workbook,
)
from app.monitoring import API_LATENCY, API_REQUESTS

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
    result = analyze_ohlcv(
        source_rows,
        from_date=from_date,
        to_date=to_date,
        benchmark_rows=benchmark_rows,
        foreign_rows=foreign_rows,
        broker_rows=broker_rows,
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


def create_app() -> FastAPI:
    app = FastAPI(title="IDX OHLCV Internal API", version="0.1.0")
    cache = OptionalCache(settings.redis_url, settings.api_cache_ttl)

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
            "return5",
            "return10",
            "return20",
            "volume_ratio20",
            "volatility20",
            "trend_score",
            "simons_score",
            "simons_label",
            "p_model",
            "p_market",
            "p_final",
            "edge",
            "foreign_net_value",
            "broker_net_value",
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

    @app.get("/ui/api/ohlcv", response_model=list[OHLCVOut])
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
        return list(
            db.scalars(
                statement.order_by(OHLCVDaily.symbol, OHLCVDaily.trade_date).limit(limit)
            )
        )

    @app.get("/ui/api/analysis")
    def ui_analysis(
        symbols: str | None = Query(None),
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        limit: int = Query(5_000, ge=1, le=20_000),
        db: Session = Depends(get_db),
    ):
        return _analysis_rows(db, symbols, from_date, to_date, limit)

    @app.get("/ui/api/broker-summary")
    def ui_broker_summary(
        symbol: str,
        from_date: date | None = Query(None, alias="from"),
        to_date: date | None = Query(None, alias="to"),
        days: int = Query(1, ge=1, le=60),
        db: Session = Depends(get_db),
    ):
        return _broker_summary_result(db, symbol, from_date, to_date, days)

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
        if dataset == "benchmark":
            loaded = upsert_benchmarks(db, rows)
        elif dataset == "foreign-flow":
            loaded = upsert_foreign_flow(db, rows)
        elif dataset == "broker-summary":
            loaded = upsert_broker_summary(db, rows)
        else:
            raise HTTPException(status_code=422, detail="dataset tidak dikenal")
        db.commit()
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
