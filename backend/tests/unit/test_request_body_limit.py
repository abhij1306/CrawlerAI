from __future__ import annotations

import pytest

from app.core import request_body_limit


async def _consume_app(scope, receive, send) -> None:
    del scope
    while True:
        message = await receive()
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def _run_request(*, path: str, chunks: list[bytes], content_length=None):
    messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]
    if not messages:
        messages = [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive():
        return messages.pop(0)

    sent: list[dict[str, object]] = []

    async def send(message):
        sent.append(message)

    headers = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers,
    }
    middleware = request_body_limit.RequestBodyLimitMiddleware(_consume_app)
    await middleware(scope, receive, send)
    return sent


@pytest.mark.asyncio
@pytest.mark.unit
async def test_rejects_advertised_oversize_before_receive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(request_body_limit.settings, "request_body_max_bytes", 4)

    sent = await _run_request(path="/api/crawls", chunks=[b""], content_length=5)

    assert sent[0]["status"] == 413


@pytest.mark.asyncio
@pytest.mark.unit
async def test_rejects_chunked_body_when_running_total_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(request_body_limit.settings, "request_body_max_bytes", 4)

    sent = await _run_request(path="/api/crawls", chunks=[b"abc", b"de"])

    assert sent[0]["status"] == 413


@pytest.mark.asyncio
@pytest.mark.unit
async def test_allows_body_at_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(request_body_limit.settings, "request_body_max_bytes", 5)

    sent = await _run_request(path="/api/crawls", chunks=[b"abc", b"de"])

    assert sent[0]["status"] == 204


@pytest.mark.asyncio
@pytest.mark.unit
async def test_replays_chunked_body_as_one_bounded_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(request_body_limit.settings, "request_body_max_bytes", 5)
    received: list[dict[str, object]] = []

    async def capture_app(scope, receive, send) -> None:
        del scope
        received.append(await receive())
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = request_body_limit.RequestBodyLimitMiddleware(capture_app)
    messages = [
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"de", "more_body": False},
    ]

    async def receive():
        return messages.pop(0)

    async def send(_message):
        return None

    await middleware(
        {"type": "http", "method": "POST", "path": "/api/crawls", "headers": []},
        receive,
        send,
    )

    assert received == [{"type": "http.request", "body": b"abcde", "more_body": False}]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_disconnect_preserves_incomplete_buffered_request_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(request_body_limit.settings, "request_body_max_bytes", 5)
    received: list[dict[str, object]] = []

    async def capture_app(scope, receive, send) -> None:
        del scope, send
        received.extend([await receive(), await receive()])

    messages = [
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive():
        return messages.pop(0)

    middleware = request_body_limit.RequestBodyLimitMiddleware(capture_app)
    await middleware(
        {"type": "http", "method": "POST", "path": "/api/crawls", "headers": []},
        receive,
        lambda _message: None,
    )

    assert received == [
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.disconnect"},
    ]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_does_not_send_second_response_after_downstream_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(request_body_limit.settings, "request_body_max_bytes", 4)

    async def started_app(scope, receive, send) -> None:
        del scope
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await receive()
        await receive()

    messages = [
        {"type": "http.request", "body": b"abcd", "more_body": False},
        {"type": "http.request", "body": b"e", "more_body": False},
    ]

    async def receive():
        return messages.pop(0)

    sent: list[dict[str, object]] = []

    async def send(message):
        sent.append(message)

    middleware = request_body_limit.RequestBodyLimitMiddleware(started_app)
    await middleware(
        {"type": "http", "method": "POST", "path": "/api/crawls", "headers": []},
        receive,
        send,
    )

    assert sent == [
        {"type": "http.response.start", "status": 204, "headers": []},
        {"type": "http.response.body", "body": b"", "more_body": False},
    ]


@pytest.mark.unit
def test_route_specific_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(request_body_limit.settings, "request_body_max_bytes", 100)
    monkeypatch.setattr(
        request_body_limit.settings, "public_api_request_body_max_bytes", 20
    )
    monkeypatch.setattr(request_body_limit.settings, "csv_upload_max_bytes", 200)
    monkeypatch.setattr(request_body_limit.settings, "multipart_overhead_max_bytes", 10)

    assert request_body_limit.request_body_limit_bytes("/api/crawls") == 100
    assert request_body_limit.request_body_limit_bytes("/api/v1/extract") == 20
    assert request_body_limit.request_body_limit_bytes("/api/crawls/csv") == 210
