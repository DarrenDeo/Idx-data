# Accessing Complete OHLCV Data IDX

Machine-readable transcription of the 20-page owner-provided PDF. The examples in
the PDF are conceptual and several source code panels were visually truncated by
the originating interface; requirements are therefore preserved without inventing
the hidden lines.

## 1. Data-source options

For direct access to complete OHLCV for all Indonesia Stock Exchange (BEI/IDX)
stocks, suitable for quantitative research, screening, backtesting, or a data
warehouse, the source options have different cost and legal characteristics.

### Official IDX source (recommended for enterprise)

IDX Data Services supplies real-time, end-of-day (EOD), and historical data. IDX
Equity EOD Data contains stock prices and trading volumes and is appropriate for
brokers, asset managers, research institutions, fintechs, and data vendors.

Official information: <https://www.idx.id/id/produk/layanan-data-bei/>

### Bulk EOD distribution

IDX also has data-distribution infrastructure where market-summary and EOD files
are published for data customers. For daily OHLCV for all issuers, bulk database
ingestion, and an automated daily update, this is generally the most stable and
legally clear route.

### Commercial APIs

Examples named in the source are OHLC.dev IDX API, IDX Edge Pro, and Kun
Data/Stocker API. Depending on provider they may offer historical OHLCV,
constituents, market summaries, broker summaries, screeners, snapshots, or
real-time WebSockets. A typical response contains:

```json
{
  "date": "2026-08-28",
  "open": 10250,
  "high": 10375,
  "low": 10125,
  "close": 10300,
  "volume": 125000000
}
```

### Low-cost research alternatives

For personal backtests, swing trading, and quantitative analysis, users often
turn to Yahoo Finance (`.JK`), Investing.com, Stockbit, or TradingView exports.
Limitations include inconsistent symbol availability, different corporate-action
adjustments, and more restrictive redistribution rights.

## 2. Recommended architecture

For a serious database covering all IDX issuers since listing:

```text
Official IDX data / chosen provider
              |
              v
       Scheduler (cron/Airflow)
              |
              v
       Get symbol list
              |
              v
       Download OHLCV
              |
              v
       Data validation
              |
              v
 DuckDB staging (when useful)
              |
              v
         PostgreSQL
              |
              v
 Backtest / screening / analytics / AI
```

The pipeline should be provider-neutral so an official feed, bulk files, or a
commercial API can be selected later.

## 3. Initial database and downloader

The initial schema consists of a symbol master and a daily OHLCV fact table:

```sql
CREATE TABLE stocks (
    symbol VARCHAR(10) PRIMARY KEY,
    company_name TEXT,
    sector TEXT
);

CREATE TABLE ohlcv_daily (
    symbol VARCHAR(10) NOT NULL,
    trade_date DATE NOT NULL,
    open NUMERIC(18,2),
    high NUMERIC(18,2),
    low NUMERIC(18,2),
    close NUMERIC(18,2),
    volume BIGINT,
    PRIMARY KEY(symbol, trade_date)
);
```

The original Python example uses `requests`, `pandas`, `sqlalchemy`, and
`psycopg2-binary`, an API key placeholder, a PostgreSQL URL, and a symbol list.
The full code panel in the source PDF is collapsed and is not reproduced as if
its hidden content were known.

Use PostgreSQL UPSERT so reruns do not create duplicates:

```sql
INSERT INTO ohlcv_daily
    (symbol, trade_date, open, high, low, close, volume)
VALUES (...)
ON CONFLICT(symbol, trade_date)
DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume;
```

Schedule the daily job after market close, at 18:00 WIB Monday-Friday. A cron
equivalent is `0 18 * * 1-5`.

Read the current universe from `SELECT symbol FROM stocks` so new IPOs do not
require code changes.

## 4. Analytical queries and scale

Daily return example:

```sql
SELECT
    symbol,
    trade_date,
    close / LAG(close) OVER (
        PARTITION BY symbol ORDER BY trade_date
    ) - 1 AS return
FROM ohlcv_daily;
```

Top-volume example:

```sql
SELECT *
FROM ohlcv_daily
WHERE trade_date = CURRENT_DATE
ORDER BY volume DESC
LIMIT 20;
```

For roughly 800-1,000 issuers and decades of history, a Python downloader,
optional DuckDB staging, PostgreSQL, and a BI or quantitative screening consumer
are sufficient. The source estimates about 4.5 million daily candles for 900
stocks over 20 years and less than 5 GB in PostgreSQL.

## 5. Production-ready requirements

The production design must handle 900+ issuers, decades of historical backfill,
incremental daily updates, automatic retries, corporate-action adjustment,
Docker deployment, PostgreSQL, Airflow, and a REST data-source abstraction.

Suggested layout:

```text
idx-platform/
├── docker-compose.yml
├── .env
├── airflow/
│   └── dags/
│       ├── sync_symbols.py
│       ├── backfill_ohlcv.py
│       └── incremental_update.py
└── app/
    └── downloader/
        ├── api_client.py
        ├── symbols.py
        └── ohlcv.py
```

Docker Compose should at minimum run PostgreSQL 16 and Airflow. PostgreSQL is the
primary structured store.

The expanded symbol master contains:

```sql
CREATE TABLE stocks (
    symbol VARCHAR(10) PRIMARY KEY,
    company_name TEXT,
    sector TEXT,
    sub_sector TEXT,
    listing_date DATE,
    active BOOLEAN DEFAULT TRUE
);
```

The expanded OHLCV table keeps the `(symbol, trade_date)` uniqueness rule.

For row counts beyond roughly 50 million, optional date range partitioning may be
used. The example creates a yearly partition such as:

```sql
CREATE TABLE ohlcv_daily (...)
PARTITION BY RANGE (trade_date);

CREATE TABLE ohlcv_2026
PARTITION OF ohlcv_daily
FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
```

## 6. Asynchronous retrieval and incremental loading

Use `asyncio` with an asynchronous HTTP client to fetch in parallel, but keep
concurrency controlled.

For each symbol, find the latest stored date:

```sql
SELECT MAX(trade_date)
FROM ohlcv_daily
WHERE symbol = 'BBCA';
```

Download only `last_date + 1` through today instead of downloading full history
each day. Use PostgreSQL conflict handling for idempotence.

## 7. Validation, errors, retry, and rate limits

Validate every clean OHLCV row:

```python
assert high >= open
assert high >= close
assert low <= open
assert low <= close
assert volume >= 0
```

Log rejected data to an audit table:

```sql
CREATE TABLE data_errors (
    id BIGSERIAL,
    symbol VARCHAR(10),
    trade_date DATE,
    error_message TEXT
);
```

Use bounded retries (the example stops after five attempts) and exponential
backoff such as 1, 2, 4, and 8 seconds. Rate-limit requests rather than issuing
uncontrolled concurrency.

## 8. Airflow

Provide a one-time or manually triggered historical-backfill DAG that iterates
all symbols from their available listing dates, and a daily-update DAG scheduled
after market close:

```python
schedule = "0 18 * * 1-5"
```

The intended timezone is WIB (`Asia/Jakarta`).

## 9. Corporate actions and adjusted prices

Corporate actions are essential for valid backtests. Store at least:

```sql
CREATE TABLE corporate_actions (
    symbol VARCHAR(10),
    ex_date DATE,
    action_type VARCHAR(50),
    ratio NUMERIC
);
```

Covered concepts include stock split, reverse split, bonus share, and rights
issue. Keep raw OHLCV unchanged and derive or materialize adjusted prices
separately. Do not fabricate action ratios.

## 10. Monitoring and indexing

Track ETL executions:

```sql
CREATE TABLE etl_runs (
    id BIGSERIAL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status VARCHAR(20),
    rows_loaded BIGINT
);
```

Operational views should distinguish success, failure, and retry states. Add the
query index:

```sql
CREATE INDEX idx_symbol_date
ON ohlcv_daily (symbol, trade_date DESC);
```

## 11. Internal API

Expose a small FastAPI service for Streamlit, Metabase, Power BI, and backtesting
consumers:

```text
GET /ohlcv/BBCA
GET /ohlcv/BBCA?from=2020-01-01
GET /symbols
GET /latest
```

## 12. Production stack

The specified production stack is Docker, PostgreSQL 16, Airflow 2.x, FastAPI,
SQLAlchemy, Pandas, Polars, DuckDB, Redis cache, Nginx, Prometheus, and Grafana.
The reference VPS size is 4 vCPU, 8 GB RAM, and 100 GB SSD.

