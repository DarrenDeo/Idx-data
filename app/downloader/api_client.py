from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
    "Referer": "https://www.idx.co.id/",
    "X-Requested-With": "XMLHttpRequest",
}


class ProviderHTTPError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AsyncIDXClient:
    def __init__(
        self,
        *,
        base_url: str,
        concurrency: int = 5,
        timeout: int = 30,
        total_timeout: int = 60,
        max_retries: int = 5,
        request_delay: float = 0.25,
        headers: dict[str, str] | None = None,
        session: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.total_timeout = total_timeout
        self.max_retries = max_retries
        self.request_delay = request_delay
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self._semaphore = asyncio.Semaphore(concurrency)
        self._session = session
        self._session_factory = session_factory
        self._owns_session = False
        self._session_ready = session is not None
        self._session_lock = asyncio.Lock()
        self._sleep = sleep

    async def __aenter__(self) -> "AsyncIDXClient":
        await self._open_session()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def _open_session(self) -> None:
        if self._session is not None:
            return
        async with self._session_lock:
            if self._session is not None:
                return
            if self._session_factory is not None:
                self._session = self._session_factory()
            else:
                from curl_cffi import requests

                self._session = requests.AsyncSession(headers=self.headers)
            self._owns_session = True
            self._session_ready = False

    async def close(self) -> None:
        async with self._session_lock:
            if not self._owns_session or self._session is None:
                return
            session = self._session
            self._session = None
            self._owns_session = False
            self._session_ready = False
        await session.close()

    def _backoff(self, retry_number: int, retry_after: str | None = None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        nominal = min(2**retry_number, 30)
        return nominal * (1 + random.uniform(0, 0.25))

    async def get_json(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        await self._open_session()

        try:
            async with asyncio.timeout(self.total_timeout):
                await self._ensure_session()
                return await self._get_json_with_retries(endpoint, params)
        except TimeoutError as exc:
            raise ProviderHTTPError(
                f"IDX request exceeded {self.total_timeout}s total timeout: {endpoint}"
            ) from exc

    async def _ensure_session(self) -> None:
        """Prime IDX cookies once, following the browser-session reference client."""

        if self._session_ready or self._session is None:
            return
        async with self._session_lock:
            if self._session_ready:
                return
            parsed = urlsplit(self.base_url)
            homepage = f"{parsed.scheme}://{parsed.netloc}/id"
            try:
                log.info("IDX session warm-up url=%s", homepage)
                async with asyncio.timeout(self.timeout):
                    response = await self._session.get(
                        homepage,
                        headers=self.headers,
                        impersonate="chrome",
                        timeout=self.timeout,
                    )
                if response.status_code >= 400:
                    log.warning("IDX session warm-up returned HTTP %s", response.status_code)
            except Exception as exc:
                # curl_cffi browser impersonation can still succeed on the API
                # when the landing page is unavailable, so warm-up is best effort.
                log.warning("IDX session warm-up failed; continuing with API request: %s", exc)
            self._session_ready = True

    async def _get_json_with_retries(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> Any:

        url = endpoint if endpoint.startswith("http") else f"{self.base_url}{endpoint}"
        async with self._semaphore:
            last_error: Exception | None = None
            for attempt in range(self.max_retries + 1):
                try:
                    log.info(
                        "IDX request endpoint=%s attempt=%d/%d timeout=%ss",
                        endpoint,
                        attempt + 1,
                        self.max_retries + 1,
                        self.timeout,
                    )
                    async with asyncio.timeout(self.timeout):
                        response = await self._session.get(
                            url,
                            params=params,
                            headers=self.headers,
                            impersonate="chrome",
                            timeout=self.timeout,
                        )
                    if response.status_code == 200:
                        if self.request_delay:
                            await self._sleep(self.request_delay)
                        return response.json()
                    if response.status_code not in RETRYABLE_STATUS:
                        raise ProviderHTTPError(
                            f"IDX returned HTTP {response.status_code} for {endpoint}",
                            response.status_code,
                        )
                    last_error = ProviderHTTPError(
                        f"retryable HTTP {response.status_code} for {endpoint}",
                        response.status_code,
                    )
                    retry_after = response.headers.get("Retry-After")
                except ProviderHTTPError:
                    raise
                except Exception as exc:  # network/JSON failures are bounded by max_retries
                    last_error = exc
                    retry_after = None

                if attempt < self.max_retries:
                    delay = self._backoff(attempt, retry_after)
                    log.warning(
                        "IDX request retry endpoint=%s attempt=%s delay=%.2fs error=%s",
                        endpoint,
                        attempt + 1,
                        delay,
                        last_error,
                    )
                    await self._sleep(delay)

            raise ProviderHTTPError(f"IDX request failed after retries: {endpoint}: {last_error}")
