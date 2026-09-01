from __future__ import annotations

import csv
import logging
import re
import time
from datetime import date
from decimal import Decimal
from io import StringIO

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.api.cache import OptionalCache
from app.api.dashboard import DASHBOARD_HTML
from app.api.jobs import JobAlreadyRunningError, JobCooldownError, job_manager
from app.config import settings
from app.database.connection import get_db
from app.database.models import ETLRun, OHLCVDaily, Stock
from app.database.queries import ohlcv_query
from app.exporting.excel import EXCEL_MIME_TYPE, build_ohlcv_workbook
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
