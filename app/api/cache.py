from __future__ import annotations

import json
import logging
from typing import Any

from redis import Redis

log = logging.getLogger(__name__)


class OptionalCache:
    def __init__(self, url: str | None, ttl: int = 60) -> None:
        self.ttl = ttl
        self.client = Redis.from_url(url, decode_responses=True, socket_timeout=0.5) if url else None

    def get(self, key: str) -> Any | None:
        if self.client is None:
            return None
        try:
            value = self.client.get(key)
            return json.loads(value) if value else None
        except Exception as exc:
            log.warning("Redis read failed open: %s", exc)
            return None

    def set(self, key: str, value: Any) -> None:
        if self.client is None:
            return
        try:
            self.client.setex(key, self.ttl, json.dumps(value, default=str))
        except Exception as exc:
            log.warning("Redis write failed open: %s", exc)

