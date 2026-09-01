# PDF Traceability

Status reflects verified repository state, not aspiration.

| Specification Requirement | Implementation | File | Status | Verification |
|---|---|---|---|---|
| Machine-readable PDF specification | Complete 20-page transcription | `docs/Accessing_Complete_OHLCV_Data_IDX.md` | DONE | Compared with extracted text and rendered pages |
| Symbol master synchronization | Provider + pipeline + UPSERT | `app/downloader/provider.py`, `app/pipeline/symbols.py` | DONE | User Docker run synchronized 962 live symbols successfully |
| Historical OHLCV backfill | Restartable per-date all-market pipeline | `app/pipeline/backfill.py` | IN_PROGRESS | Month rerun completed with 12,057 loaded, 2,472 skipped, and zero request failures; 3,768 positive-volume rows lack an upstream open price |
| Incremental daily update | `MAX(trade_date) + 1` logic | `app/pipeline/incremental.py` | DONE | Date calculation and idempotence tests passed in Docker |
| Controlled async retrieval | Semaphore/configuration | `app/downloader/api_client.py`, `app/pipeline/backfill.py` | DONE | Persistent-session regression passed and all 21 weekday requests completed with zero failures |
| Retry/backoff/rate-limit handling | Bounded HTTP retry | `app/downloader/api_client.py` | DONE | Dependency-free retry/404 smoke passed; pytest coverage present |
| OHLCV validation | Explicit rules plus no-trade classification | `app/validation/ohlcv.py` | DONE | 2,472 no-trade rows skipped; all 3,768 rejects verified as positive-volume rows with both open and first trade equal to zero |
| PostgreSQL primary storage | PostgreSQL 16 schema and SQLAlchemy | `sql/init.sql`, `app/database/models.py` | DONE | Healthy PostgreSQL 16 runtime, schema initialization, and symbol persistence confirmed |
| Idempotent UPSERT | Conflict update on symbol/date | `app/database/queries.py` | DONE | UPSERT and duplicate-prevention tests passed in Docker |
| Validation audit | `data_errors` storage | `app/database/models.py` | DONE | Database-backed pipeline tests passed in Docker |
| Corporate actions | Separate raw action storage | `app/downloader/corporate_actions.py` | IN_PROGRESS | Endpoint parser/persistence implemented; live payload unavailable |
| Adjusted price concept | Separate materialization from explicit ratios | `app/pipeline/adjustments.py` | IN_PROGRESS | Implemented without inventing ratios; database test blocked |
| Airflow DAGs | Sync, manual backfill, incremental | `airflow/dags/` | DONE | DAG contract tests pass; init completed and scheduler/webserver run |
| 18:00 WIB Monday-Friday | Pendulum timezone DAG schedule | `airflow/dags/incremental_update.py` | DONE | Source compiled with `0 18 * * 1-5` and `Asia/Jakarta` |
| DuckDB staging | Optional batch/local stage | `app/pipeline/staging.py` | DONE | Docker dependency installation and staging tests passed |
| FastAPI endpoints | Symbols, OHLCV, latest, health, ETL runs | `app/api/main.py` | DONE | All TestClient tests passed and API runtime reports healthy |
| Query index | `(symbol, trade_date DESC)` | `sql/init.sql` | DONE | DDL present; Compose config validates mount |
| Docker deployment | Compose + API/Airflow/test images | `docker-compose.yml` | DONE | Revised images built; all nine services started with API/PostgreSQL healthy |
| Optional Redis cache | Fail-open API caching | `app/api/cache.py` | DONE | Redis and healthy API runtime confirmed; fail-open behavior covered by API tests |
| Nginx reverse proxy | Single upstream | `nginx/nginx.conf` | DONE | Compose config passes and service wiring is present |
| Prometheus metrics | API and ETL metrics | `app/monitoring.py` | DONE | Metrics tests pass and Prometheus runs on host port 19090 |
| Grafana dashboard | Practical basic dashboard | `monitoring/grafana/` | DONE | Dashboard JSON parses and provisioning validates through Compose |
| Live IDX endpoint investigation | Endpoint/header/result report | `docs/DATA_SOURCE.md` | IN_PROGRESS | Symbol endpoint returned 962 symbols and daily endpoint returned 963 market rows; corporate-action sample pending |
| Automated tests | Pytest suite + Docker test target | `tests/`, `Dockerfile` | DONE | Current Docker image passed all 31 tests on 2026-09-01 |
| CSV/XLSX export | Browser form and filtered downloads | `app/api/main.py`, `app/exporting/excel.py` | DONE | CSV values checked; XLSX imported, rendered, visually inspected, and opened with openpyxl |
| Lightweight Pop!_OS server | Restart policies, scheduler, backup and migration guide | `docker-compose.yml`, `app/scheduler.py`, `docs/POP_OS_DEPLOYMENT.md` | DONE | Core/server/Airflow/monitoring Compose configurations validated |
