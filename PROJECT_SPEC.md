# IDX OHLCV Platform - Project Specification

## Goal

Build a clean, restartable platform that synchronizes the IDX equity universe,
backfills and incrementally updates daily raw OHLCV data, validates it, stores it
idempotently in PostgreSQL 16, and exposes a small internal FastAPI API.

## Required behavior

- Synchronize stock symbols with company name, sector, sub-sector, listing date,
  and active status when available.
- Retrieve historical and daily OHLCV through a small swappable provider
  interface.
- Use configurable, bounded asynchronous concurrency, timeouts, retries,
  exponential backoff, and handling for HTTP 429/500/502/503/504.
- Validate `high >= open`, `high >= close`, `low <= open`, `low <= close`, and
  `volume >= 0`; structurally invalid rows go to `data_errors`.
- Use PostgreSQL UPSERT keyed by `(symbol, trade_date)` so reruns are idempotent.
- Backfill each symbol independently and preserve successful progress if another
  symbol fails.
- Increment from `MAX(trade_date) + 1` through the requested end date.
- Store corporate actions separately from raw OHLCV. Adjusted prices are a
  separate materialization and are calculated only from explicit usable ratios.
- Provide Airflow DAGs for symbol sync, manual backfill, and weekday incremental
  updates at 18:00 `Asia/Jakarta`.
- Provide `GET /symbols`, `GET /ohlcv/{symbol}` (including `from`), `GET /latest`,
  `GET /health`, and `GET /etl-runs`; keep Swagger at `/docs`.
- Run through Docker Compose with PostgreSQL 16, the API, Airflow, Redis, Nginx,
  Prometheus, and a basic Grafana dashboard. Redis is an optional cache and may
  never be required for correctness.
- Keep DuckDB optional and limited to staging/local analytical work; PostgreSQL
  remains the relational source of truth.
- Log job name, symbol/range where applicable, fetched/loaded/rejected row counts,
  retries, duration, and status. Persist ETL-run status.
- Test validation, provider parsing, retry behavior, UPSERT/duplicate prevention,
  incremental date calculation, and FastAPI endpoints.

## Explicit non-goals

No Kubernetes, Kafka, microservices, complex DDD, serverless architecture,
unrelated analytics, AI assistants, Neo4j, UBO graphs, bandarmology, news systems,
or unnecessary authentication/frontend frameworks.

## Data-source constraint

The built-in public IDX provider uses the current endpoint patterns found in the
two owner-named reference repositories. Direct public access is not guaranteed:
IDX may require browser cookies or impersonation, may rate-limit or block a host,
and its terms must be respected. A commercial or official feed can replace it
without changing pipeline and database code.

