from prometheus_client import Counter, Gauge, Histogram

API_REQUESTS = Counter("idx_api_requests_total", "API requests", ["method", "path", "status"])
API_LATENCY = Histogram("idx_api_request_duration_seconds", "API request latency", ["path"])
ETL_SUCCESSES = Counter("idx_etl_success_total", "Successful ETL jobs", ["job"])
ETL_FAILURES = Counter("idx_etl_failure_total", "Failed ETL jobs", ["job"])
ETL_ROWS = Counter("idx_etl_rows_loaded_total", "Rows loaded", ["job"])
LAST_INGESTION = Gauge("idx_last_successful_ingestion_timestamp", "Last successful ETL time")


def record_etl_result(job: str, status: str, rows_loaded: int) -> None:
    ETL_ROWS.labels(job).inc(rows_loaded)
    if status == "SUCCESS":
        ETL_SUCCESSES.labels(job).inc()
        LAST_INGESTION.set_to_current_time()
    else:
        ETL_FAILURES.labels(job).inc()
