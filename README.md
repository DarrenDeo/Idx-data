# IDX OHLCV Platform

A small, restartable Python/PostgreSQL platform for IDX symbol synchronization,
historical daily OHLCV backfill, incremental updates, validation, corporate
actions, Airflow scheduling, and an internal FastAPI service.

The implementation follows [PROJECT_SPEC.md](PROJECT_SPEC.md) and the complete
owner specification transcription in
[docs/Accessing_Complete_OHLCV_Data_IDX.md](docs/Accessing_Complete_OHLCV_Data_IDX.md).
Implementation status and evidence are tracked in
[PDF_TRACEABILITY.md](PDF_TRACEABILITY.md).

## Architecture

```text
IDX / replaceable provider
          |
          v
 Airflow + async downloader
          |
          v
 validation + optional DuckDB stage
          |
          v
 PostgreSQL 16 (raw source of truth)
          |
          v
FastAPI + Excel export -> optional Redis cache -> Nginx
          |
          v
 Prometheus + Grafana
```

Raw OHLCV is never overwritten by corporate-action adjustment. The separate
`adjusted_prices` table is materialized only from explicit, positive, split-like
ratios; rights issues without complete terms remain unadjusted.

## Quick start with Docker Compose

Prerequisites: Docker Desktop/Engine with Compose v2.

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace every `change-me` password. Then:

```powershell
docker compose down --remove-orphans
docker compose build
docker compose up -d postgres redis api
docker compose exec api idx-platform init-db
docker compose exec api idx-platform sync-symbols
docker compose --profile server up -d
```

PostgreSQL is exposed only on `127.0.0.1:55432` by default so it does not
collide with an existing local PostgreSQL installation on port 5432. Change
`POSTGRES_HOST_PORT` in `.env` if 55432 is also occupied. Containers continue to
use the internal address `postgres:5432`. Other browser-facing services also
use configurable localhost-only ports to avoid common development-port
collisions.

Services:

| Service | URL |
|---|---|
| Web dashboard | <http://localhost/> |
| Swagger | <http://localhost/docs> |
| CSV / Excel export | Available from the dashboard |
| Airflow | <http://localhost:18080> |
| Grafana | <http://localhost:13000> |
| Prometheus | <http://localhost:19090> |

Override `API_HOST_PORT`, `AIRFLOW_HOST_PORT`, `GRAFANA_HOST_PORT`, or
`PROMETHEUS_HOST_PORT` in `.env` when needed. These settings change only host
access; service-to-service traffic continues to use the standard container
ports.

The API remains correct when Redis is unavailable; cache failures fall through to
PostgreSQL.

The default lightweight server profile runs a safe 18:00 WIB weekday market
update. It starts after the latest date already stored globally, so a partially
seeded database does not accidentally trigger a listing-date backfill for every
symbol. Airflow and monitoring are optional profiles:

```powershell
docker compose --profile airflow --profile monitoring up -d --build
```

Do not run the `server` and `airflow` profiles together because they schedule the
same daily market update.

## Local Python setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
idx-platform init-db
```

For local PostgreSQL, set `DATABASE_URL` to a reachable PostgreSQL 16 database.
`sql/init.sql` is also safe to run through `psql` on a fresh database.
When connecting from the host to the Compose database, use port 55432 (or your
configured `POSTGRES_HOST_PORT`).

## Data commands

Synchronize the current symbol list:

```powershell
idx-platform sync-symbols
```

Small historical verification first:

```powershell
idx-platform backfill --symbols BBCA BBRI TLKM --start 2026-08-24 --end 2026-08-28
```

Backfill requests `GetStockSummary` once per weekday and filters the returned
all-market payload when `--symbols` is present. Without `--symbols`, every
returned security is retained, including historical-only tickers; unknown
tickers are created as inactive placeholders without overwriting synchronized
company metadata. Rows with zero executed volume are classified as no-trade and
reported as `rows_skipped`; they are neither fabricated into candles nor logged
as validation errors. Positive-volume rows for which IDX reports both
`OpenPrice = 0` and `FirstTrade = 0` remain quarantined in `data_errors`, because
there is no truthful opening price to persist. Each date commits independently
for safe restart.

Full backfill capability (do this only after the small test succeeds):

```powershell
idx-platform backfill --start 2000-01-01 --end 2026-08-31
```

Increment from each symbol's stored maximum date:

```powershell
idx-platform incremental --end 2026-08-31
idx-platform incremental --end 2026-08-31
```

The second identical run must leave the `(symbol, trade_date)` row count unchanged.
On an incompletely seeded database, symbols without any OHLCV fall back to their
listing dates, so the first incremental run is intentionally a potentially large
historical catch-up. Complete or deliberately scope the baseline backfill first.

Run the server-safe all-market update used by the scheduler:

```powershell
idx-platform daily --end 2026-08-31
```

This starts at the day after the latest date stored anywhere in `ohlcv_daily`.
Use `backfill` when you intentionally need to fill an older historical gap.

Corporate actions and adjusted price materialization:

```powershell
idx-platform corporate-actions --symbols BBCA --start 2000-01-01 --end 2026-08-31
idx-platform adjust BBCA
```

## Airflow

- `idx_sync_symbols`: weekdays at 17:00 Asia/Jakarta.
- `idx_incremental_update`: weekdays at 18:00 Asia/Jakarta; its retained DAG
  name now invokes the safe global-date `daily` command.
- `idx_backfill_ohlcv`: manual only; start and end dates are validated parameters
  in Airflow's trigger form.

The Airflow image keeps Airflow's required SQLAlchemy 1.4 environment unchanged.
ETL commands run from an isolated application virtual environment inside the
same container.

Weekends and market holidays can legitimately return no rows and are not fatal.

## Web dashboard

Open <http://localhost/> after the server starts. The dashboard replaces the
most common terminal commands with buttons:

- filter and display OHLCV data for one or more symbols;
- synchronize the IDX symbol list;
- run the safe daily market update;
- backfill up to 20 selected symbols for a date range;
- inspect the current process output and recent ETL status; and
- download the currently selected symbols and dates as CSV or formatted Excel.

Only one data operation can run at a time. Closing the browser does not stop an
operation already started by the dashboard. The API container continues the job
and the status appears again when the dashboard is reopened. UI-started jobs also
have a 30-second global cooldown to reduce accidental or repeated submissions.

The `server` profile also starts `public-nginx` on host-only port `18474`. It is
intended as the local target for an HTTPS Tailscale Funnel. Swagger, OpenAPI,
Prometheus metrics, and Redoc are not exposed through this public gateway; the
dashboard, data queries, exports, and guarded scraping controls remain available.

## API

```text
GET /health
GET /symbols
GET /ohlcv/BBCA
GET /ohlcv/BBCA?from=2020-01-01
GET /ohlcv/BBCA?from=2020-01-01&to=2020-12-31
GET /latest
GET /etl-runs
GET /export
GET /export/ohlcv.csv?symbols=BBCA,BBRI,TLKM&from=2026-08-24&to=2026-08-28
GET /export/ohlcv.xlsx?symbols=BBCA,BBRI,TLKM&from=2026-08-24&to=2026-08-28
GET /docs
```

The dashboard at `/` offers CSV (small, fast, and Excel-compatible) or a
formatted `.xlsx` workbook with a summary sheet and validated OHLCV data sheet.
CSV includes an explicit `currency=IDR` field while keeping prices numeric.
XLSX displays price columns as Rupiah, volume with thousands separators, and
price changes as percentages. A file is limited to 100,000 rows; split large
exports by symbol or date range.

## Pop!_OS always-on server

The complete lightweight self-hosting, private Tailscale access, restart, update,
and backup instructions are in
[`docs/POP_OS_DEPLOYMENT.md`](docs/POP_OS_DEPLOYMENT.md).

## Tests and validation

```powershell
python -m pytest
docker compose --profile test run --build --rm tests
docker compose config --quiet
```

The Dockerized test command is the recommended option when the host virtual
environment does not have the development dependencies installed.

The pytest suite covers OHLC validation, provider parsing, bounded retry,
PostgreSQL-compatible UPSERT behavior using SQLite, duplicate prevention,
incremental and daily date calculation, restartable backfill, Excel export,
scheduler timing, and every required FastAPI endpoint. SQLite is a fast unit-test
substitute only; PostgreSQL remains the production source of truth.

For a real PostgreSQL idempotence check:

```sql
SELECT symbol, trade_date, COUNT(*)
FROM ohlcv_daily
GROUP BY symbol, trade_date
HAVING COUNT(*) > 1;
```

The query must return zero rows.

## Data-source status and legal note

The current public endpoint patterns, headers, reference review, and the failed
host-level live access attempt are documented in
[docs/DATA_SOURCE.md](docs/DATA_SOURCE.md). This repository does not claim live
IDX access when it has not been verified. Review IDX terms and obtain appropriate
official/commercial data rights before commercial use or redistribution.

## Operational guidance

- Keep `IDX_CONCURRENCY` conservative (default `5`).
- `IDX_TOTAL_TIMEOUT` bounds each endpoint operation to 60 seconds by default,
  including retries and backoff.
- One browser session is shared for the command lifetime and closed only after
  all concurrent requests finish.
- Start with a short date range and a few symbols.
- Monitor `data_errors` and `etl_runs` after each run.
- A date failure in daily bulk mode is isolated; successful dates commit
  independently and an idempotent rerun fills the gap.
- Use the manual Airflow backfill only after symbol sync and a small live test.
- Date range partitioning is intentionally deferred until the fact table grows
  toward the specification's approximately 50-million-row threshold.
