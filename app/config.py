from __future__ import annotations

import os
from dataclasses import dataclass


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, default))
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    idx_base_url: str
    idx_concurrency: int
    idx_request_timeout: int
    idx_total_timeout: int
    idx_max_retries: int
    idx_request_delay: float
    redis_url: str | None
    api_cache_ttl: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        redis_url = os.getenv("REDIS_URL") or None
        return cls(
            database_url=os.getenv(
                "DATABASE_URL", "postgresql+psycopg://idx:idx@localhost:5432/idx"
            ),
            idx_base_url=os.getenv("IDX_BASE_URL", "https://www.idx.co.id/primary").rstrip("/"),
            idx_concurrency=_positive_int("IDX_CONCURRENCY", 5),
            idx_request_timeout=_positive_int("IDX_REQUEST_TIMEOUT", 30),
            idx_total_timeout=_positive_int("IDX_TOTAL_TIMEOUT", 60),
            idx_max_retries=_positive_int("IDX_MAX_RETRIES", 5),
            idx_request_delay=max(0.0, float(os.getenv("IDX_REQUEST_DELAY", "0.25"))),
            redis_url=redis_url,
            api_cache_ttl=_positive_int("API_CACHE_TTL", 60),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )


settings = Settings.from_env()
