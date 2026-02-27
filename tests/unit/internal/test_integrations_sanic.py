from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

pytest.importorskip("sanic")

from sanic.response import text

import diwire._internal.integrations.sanic as sanic_integration
from diwire import Container
from diwire.exceptions import DIWireIntegrationError


class _FakeRequest:
    def __init__(self, path: str = "/") -> None:
        self.path = path
        self.ctx = SimpleNamespace()


class _FakeWebsocket:
    pass


def test_get_connection_raises_when_context_is_missing() -> None:
    with pytest.raises(DIWireIntegrationError, match="Connection context not available"):
        sanic_integration.get_connection()


def test_get_request_raises_when_current_connection_is_not_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sanic_integration, "Request", _FakeRequest)
    monkeypatch.setattr(sanic_integration, "Websocket", _FakeWebsocket)
    token = sanic_integration._websocket_context.set(cast("Any", _FakeWebsocket()))
    try:
        with pytest.raises(DIWireIntegrationError, match="not HTTP Request"):
            sanic_integration.get_request()
    finally:
        sanic_integration._websocket_context.reset(token)


def test_get_websocket_raises_when_current_connection_is_not_websocket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sanic_integration, "Request", _FakeRequest)
    monkeypatch.setattr(sanic_integration, "Websocket", _FakeWebsocket)
    token = sanic_integration._request_context.set(cast("Any", _FakeRequest("/request")))
    try:
        with pytest.raises(DIWireIntegrationError, match="not WebSocket"):
            sanic_integration.get_websocket()
    finally:
        sanic_integration._request_context.reset(token)


def test_get_connection_prefers_websocket_when_both_contexts_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sanic_integration, "Request", _FakeRequest)
    monkeypatch.setattr(sanic_integration, "Websocket", _FakeWebsocket)

    request = _FakeRequest("/request")
    websocket = _FakeWebsocket()
    request_token = sanic_integration._request_context.set(cast("Any", request))
    websocket_token = sanic_integration._websocket_context.set(cast("Any", websocket))
    try:
        assert cast("Any", sanic_integration.get_connection()) is websocket
    finally:
        sanic_integration._websocket_context.reset(websocket_token)
        sanic_integration._request_context.reset(request_token)


def test_get_connection_returns_request_when_only_request_context_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sanic_integration, "Request", _FakeRequest)

    request = _FakeRequest("/request")
    request_token = sanic_integration._request_context.set(cast("Any", request))
    try:
        assert cast("Any", sanic_integration.get_connection()) is request
    finally:
        sanic_integration._request_context.reset(request_token)


@pytest.mark.asyncio
async def test_request_and_response_middleware_manage_request_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sanic_integration, "Request", _FakeRequest)
    request = _FakeRequest("/middleware/http")

    await sanic_integration.request_context_middleware(cast("Any", request))

    assert cast("Any", sanic_integration.get_request()) is request

    await sanic_integration.response_context_middleware(cast("Any", request), text("ok"))

    with pytest.raises(DIWireIntegrationError, match="Connection context not available"):
        sanic_integration.get_connection()


@pytest.mark.asyncio
async def test_response_context_middleware_is_noop_when_request_token_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sanic_integration, "Request", _FakeRequest)
    request = _FakeRequest("/middleware/http-noop")

    await sanic_integration.response_context_middleware(cast("Any", request), text("ok"))

    with pytest.raises(DIWireIntegrationError, match="Connection context not available"):
        sanic_integration.get_connection()


@pytest.mark.asyncio
async def test_websocket_signal_handlers_manage_context_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sanic_integration, "Request", _FakeRequest)
    monkeypatch.setattr(sanic_integration, "Websocket", _FakeWebsocket)

    request = _FakeRequest("/middleware/websocket")
    websocket = _FakeWebsocket()

    await sanic_integration.request_context_middleware(cast("Any", request))
    await sanic_integration._websocket_context_before(cast("Any", request), cast("Any", websocket))

    assert cast("Any", sanic_integration.get_websocket()) is websocket

    await sanic_integration._websocket_context_after(cast("Any", request), cast("Any", websocket))

    with pytest.raises(DIWireIntegrationError, match="Connection context not available"):
        sanic_integration.get_connection()


@pytest.mark.asyncio
async def test_websocket_exception_handler_resets_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sanic_integration, "Request", _FakeRequest)
    monkeypatch.setattr(sanic_integration, "Websocket", _FakeWebsocket)

    request = _FakeRequest("/middleware/websocket-error")
    websocket = _FakeWebsocket()

    await sanic_integration.request_context_middleware(cast("Any", request))
    await sanic_integration._websocket_context_before(cast("Any", request), cast("Any", websocket))
    await sanic_integration._websocket_context_exception(
        cast("Any", request),
        cast("Any", websocket),
        RuntimeError("boom"),
    )

    with pytest.raises(DIWireIntegrationError, match="Connection context not available"):
        sanic_integration.get_connection()


@pytest.mark.asyncio
async def test_websocket_after_handler_is_noop_when_websocket_token_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sanic_integration, "Request", _FakeRequest)
    monkeypatch.setattr(sanic_integration, "Websocket", _FakeWebsocket)

    request = _FakeRequest("/middleware/websocket-no-token")
    websocket = _FakeWebsocket()

    await sanic_integration.request_context_middleware(cast("Any", request))
    await sanic_integration._websocket_context_after(cast("Any", request), cast("Any", websocket))

    with pytest.raises(DIWireIntegrationError, match="Connection context not available"):
        sanic_integration.get_connection()


def test_add_request_context_registers_factories_for_container_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sanic_integration, "Request", _FakeRequest)
    monkeypatch.setattr(sanic_integration, "Websocket", _FakeWebsocket)
    monkeypatch.setattr(sanic_integration, "_REQUEST_PROVIDER_KEY", _FakeRequest)
    monkeypatch.setattr(sanic_integration, "_WEBSOCKET_PROVIDER_KEY", _FakeWebsocket)

    container = Container()
    sanic_integration.add_request_context(container)

    request = _FakeRequest("/container/request")
    request_token = sanic_integration._request_context.set(cast("Any", request))
    try:
        resolved_request = container.resolve(_FakeRequest)
        assert resolved_request is request
    finally:
        sanic_integration._request_context.reset(request_token)

    websocket = _FakeWebsocket()
    websocket_token = sanic_integration._websocket_context.set(cast("Any", websocket))
    try:
        resolved_websocket = container.resolve(_FakeWebsocket)
        assert resolved_websocket is websocket
    finally:
        sanic_integration._websocket_context.reset(websocket_token)


def test_install_request_context_is_idempotent() -> None:
    from sanic import Sanic

    app = Sanic("diwire_sanic_internal_install")
    sanic_integration.install_request_context(app)

    request_middleware_count = len(app.request_middleware)
    response_middleware_count = len(app.response_middleware)

    sanic_integration.install_request_context(app)

    assert len(app.request_middleware) == request_middleware_count
    assert len(app.response_middleware) == response_middleware_count
