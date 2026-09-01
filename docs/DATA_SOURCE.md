# IDX Data Source Investigation

Investigation date: 2026-08-31 (Asia/Jakarta).

## References reviewed

- [`nichsedge/idx-bei`](https://github.com/nichsedge/idx-bei), specifically
  `python/src/idx/core/client.py`, `scrapers/historical.py`, `scrapers/trading.py`,
  `scrapers/corporate.py`, and `pipelines/daily.py`.
- [`NeaByteLab/IDX-API`](https://github.com/NeaByteLab/IDX-API), specifically
  `src/Client.ts`, the trading/company modules, and the StockSummary,
  CompanyProfile, and IssuedHistory synchronizers.

Both are MIT-licensed implementation references. This project reimplements the
small necessary behavior and does not copy unrelated features or source files.

The source-level review was repeated against these exact commits:

- `nichsedge/idx-bei`: `385caad9557eebb2a20f39ccc0e8ea5683d7abc7`
- `NeaByteLab/IDX-API`: `910b8db70893b93920a1bba331d00a1a245907c6`

Patterns adopted from the references include browser impersonation, a one-time
IDX cookie/session warm-up, bounded retry and throttling, weekday generation,
date-oriented `GetStockSummary` backfill, per-date commits, and conflict-safe
persistence. The project keeps its own PostgreSQL, validation, audit, Airflow,
and FastAPI design rather than copying either reference architecture.

## Endpoint patterns implemented

Base URL: `https://www.idx.co.id/primary`

| Capability | Endpoint | Parameters | Expected collection |
|---|---|---|---|
| Symbol master | `/ListedCompany/GetCompanyProfiles` | `start=0`, `length=9999` | `data` |
| Primary historical/daily OHLCV | `/TradingSummary/GetStockSummary` | `date=YYYYMMDD`, `start=0`, `length=9999` | `data` |
| Secondary per-symbol history view | `/ListedCompany/GetTradingInfoSS` | `code=BBCA`, `start`, `length` | `replies` |
| Issuance/corporate history | `/ListingActivity/GetIssuedHistory` | `kodeEmiten=BBCA`, `start=0`, `length=9999` | `data` |

Expected OHLCV field names are `StockCode`, `Date`, `OpenPrice`, `High`, `Low`,
`Close`, and `Volume`. The provider retains each raw row for audit on rejection.

## Request behavior

Reference clients use browser-like headers:

- `Accept: application/json, text/plain, */*`
- `Accept-Language`
- `Referer: https://www.idx.co.id/`
- `X-Requested-With: XMLHttpRequest`
- a current browser user agent

The primary reference uses `curl_cffi` Chrome impersonation, controlled
concurrency, a post-request delay, and exponential backoff with jitter. The
secondary reference first visits the IDX home page to obtain cookies and retries
server errors with capped exponential delay. This project now does both and also
enforces an independent 60-second total deadline around an endpoint operation.
The warmed browser session remains open for the full CLI command, so one
concurrent request cannot close it while another request is retrying.

Backfill follows `idx-bei`'s historical pipeline: generate weekdays, request the
all-market stock summary once per date, and persist each successful date before
moving on. Explicit `--symbols` values filter that daily payload; omitting the
flag retains every returned security, including historical-only tickers absent
from the current active-company list. Daily rows with `Volume = 0` represent no
executed trade and are counted as skipped rather than persisted as synthetic
candles or written to the validation-error table.

The user's verified 2026-08 run also exposed an upstream completeness boundary:
3,768 rows had positive volume but both `OpenPrice = 0` and `FirstTrade = 0`.
Every one failed only the `low > open` invariant. The inspected GitHub reference
snapshot contains the same provider shape and neither supplied project recovers
an alternate historical opening price. These rows therefore remain quarantined;
using low, close, or previous close as open would fabricate data.

## Small BBCA live test

Target date: 2026-08-28. Target URL pattern:

```text
GET /TradingSummary/GetStockSummary?date=20260828&start=0&length=9999
```

Observed outcomes from this host:

1. PowerShell and curl could not open a socket to `www.idx.co.id:443` because the
   execution environment denied the connection.
2. The in-app browser attempted the exact public endpoint but returned
   `ERR_BLOCKED_BY_CLIENT`.

The original agent host could not reach the endpoint. The user's rebuilt Docker
runtime subsequently completed the same test: session warm-up succeeded, the
daily endpoint returned 963 market rows, BBCA was selected, and one row was
persisted with zero validation or provider failures.

```powershell
idx-platform backfill --symbols BBCA --start 2026-08-28 --end 2026-08-28
```

The persisted row can be verified with:

```sql
SELECT symbol, trade_date, open, high, low, close, volume
FROM ohlcv_daily
WHERE symbol = 'BBCA' AND trade_date = DATE '2026-08-28';
```

## Known limitations

- IDX may enforce Cloudflare/browser checks, host blocking, cookies, or rate
  limits without notice.
- Endpoint schemas and availability are not a contractual data feed.
- Historical depth returned by `GetTradingInfoSS` is not relied upon for the
  primary backfill. It remains available as a secondary provider method.
- The public daily summary can omit open and first-trade prices even when volume
  is positive. Complete coverage of those candles requires a different official
  or licensed source, or historical tick data from which the first trade can be
  calculated.
- The public issued-history response may not contain a usable split ratio. Such
  actions are stored with `ratio = NULL`; adjusted prices are not fabricated.
- Market holidays legitimately produce no daily records and should not be treated
  as fatal failures.
- Review IDX terms and obtain an official/commercial license before commercial
  redistribution. The official site states restrictions on commercial use and
  dissemination without prior written consent.
