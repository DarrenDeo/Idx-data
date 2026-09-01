import asyncio

import pytest

from app.downloader.api_client import AsyncIDXClient, ProviderHTTPError


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.closed = False

    async def get(self, *args, **kwargs):
        self.calls += 1
        return self.responses.pop(0)

    async def close(self):
        self.closed = True


class HangingSession:
    async def get(self, *args, **kwargs):
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_retryable_status_is_retried():
    sleeps = []

    async def sleep(value):
        sleeps.append(value)

    session = FakeSession([FakeResponse(503), FakeResponse(200, {"data": []})])
    client = AsyncIDXClient(
        base_url="https://example.invalid",
        max_retries=2,
        request_delay=0,
        session=session,
        sleep=sleep,
    )
    assert await client.get_json("/test") == {"data": []}
    assert session.calls == 2
    assert len(sleeps) == 1


@pytest.mark.asyncio
async def test_nonretryable_status_fails_immediately():
    session = FakeSession([FakeResponse(404)])
    client = AsyncIDXClient(
        base_url="https://example.invalid", max_retries=5, request_delay=0, session=session
    )
    with pytest.raises(ProviderHTTPError) as error:
        await client.get_json("/missing")
    assert error.value.status_code == 404
    assert session.calls == 1


@pytest.mark.asyncio
async def test_total_timeout_bounds_a_hanging_transport():
    client = AsyncIDXClient(
        base_url="https://example.invalid",
        timeout=1,
        total_timeout=0.01,
        max_retries=5,
        request_delay=0,
        session=HangingSession(),
    )
    with pytest.raises(ProviderHTTPError, match="exceeded .* total timeout"):
        await client.get_json("/hang")


@pytest.mark.asyncio
async def test_owned_session_is_warmed_once_before_api_requests():
    session = FakeSession(
        [
            FakeResponse(200),
            FakeResponse(200, {"data": [1]}),
            FakeResponse(200, {"data": [2]}),
        ]
    )
    client = AsyncIDXClient(
        base_url="https://www.idx.co.id/primary",
        max_retries=0,
        request_delay=0,
        session=session,
    )
    client._session_ready = False

    assert await client.get_json("/first") == {"data": [1]}
    assert await client.get_json("/second") == {"data": [2]}
    assert session.calls == 3


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_owned_session_until_explicit_close():
    sessions = []

    class ConcurrentSession(FakeSession):
        async def get(self, *args, **kwargs):
            await asyncio.sleep(0)
            return await super().get(*args, **kwargs)

    def session_factory():
        session = ConcurrentSession(
            [
                FakeResponse(200),
                FakeResponse(200, {"data": [1]}),
                FakeResponse(200, {"data": [2]}),
            ]
        )
        sessions.append(session)
        return session

    client = AsyncIDXClient(
        base_url="https://www.idx.co.id/primary",
        concurrency=2,
        max_retries=0,
        request_delay=0,
        session_factory=session_factory,
    )

    async with client:
        results = await asyncio.gather(client.get_json("/first"), client.get_json("/second"))
        assert results == [{"data": [1]}, {"data": [2]}]
        assert len(sessions) == 1
        assert sessions[0].closed is False

    assert sessions[0].calls == 3
    assert sessions[0].closed is True
