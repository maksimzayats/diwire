from __future__ import annotations

import importlib
from collections.abc import MutableMapping
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("starlette")

from starlette.requests import Request, StateT
from starlette.websockets import WebSocket

import diwire._internal.integrations.fastapi as fastapi_integration
from diwire import Container, Lifetime, Scope
from diwire.exceptions import DIWireIntegrationError


def _build_http_scope(path: str = "/") -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "state": {},
    }


def _build_websocket_scope(path: str = "/ws") -> dict[str, Any]:
    return {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "subprotocols": [],
        "state": {},
    }


def _request_for_scope(path: str = "/") -> Request:
    return Request(_build_http_scope(path))


def _websocket_for_scope(path: str = "/ws") -> WebSocket:
    async def _receive() -> MutableMapping[str, Any]:
        return {"type": "websocket.disconnect", "code": 1000}

    async def _send(_message: MutableMapping[str, Any]) -> None:
        return None

    return WebSocket(
        _build_websocket_scope(path),
        receive=_receive,
        send=_send,
    )


def test_get_connection_raises_when_context_is_missing() -> None:
    with pytest.raises(DIWireIntegrationError, match="Connection context not available"):
        fastapi_integration.get_connection(dict)


def test_get_request_raises_when_current_connection_is_not_http_request() -> None:
    token = fastapi_integration._connection_context.set(_websocket_for_scope("/websocket"))
    try:
        with pytest.raises(DIWireIntegrationError, match="not HTTP Request"):
            fastapi_integration.get_request(dict)
    finally:
        fastapi_integration._connection_context.reset(token)


def test_get_websocket_typed_raises_when_current_connection_is_not_websocket() -> None:
    token = fastapi_integration._connection_context.set(_request_for_scope("/request"))
    try:
        with pytest.raises(DIWireIntegrationError, match="not WebSocket"):
            fastapi_integration._get_websocket_typed(dict)
    finally:
        fastapi_integration._connection_context.reset(token)


def test_get_websocket_typed_returns_current_websocket_connection() -> None:
    websocket = _websocket_for_scope("/websocket")
    token = fastapi_integration._connection_context.set(websocket)
    try:
        resolved = fastapi_integration._get_websocket_typed(dict)
        assert resolved is websocket
    finally:
        fastapi_integration._connection_context.reset(token)


def test_get_websocket_untyped_raises_when_current_connection_is_not_websocket() -> None:
    token = fastapi_integration._connection_context.set(_request_for_scope("/request"))
    try:
        with pytest.raises(DIWireIntegrationError, match="not WebSocket"):
            fastapi_integration._get_websocket_untyped()
    finally:
        fastapi_integration._connection_context.reset(token)


def test_get_websocket_selector_chooses_typed_path_when_state_typevar_is_present(
    monkeypatch: Any,
) -> None:
    module = importlib.reload(fastapi_integration)
    monkeypatch.setattr(
        module.WebSocket,
        "__orig_bases__",
        (SimpleNamespace(__args__=(StateT,)),),
        raising=False,
    )

    reloaded = importlib.reload(module)

    assert reloaded.get_websocket is reloaded._get_websocket_typed


def test_get_websocket_selector_falls_back_to_untyped_path_when_state_typevar_is_absent(
    monkeypatch: Any,
) -> None:
    module = importlib.reload(fastapi_integration)
    monkeypatch.setattr(
        module.WebSocket,
        "__orig_bases__",
        (SimpleNamespace(__args__=(object(),)),),
        raising=False,
    )

    reloaded = importlib.reload(module)

    assert reloaded.get_websocket is reloaded._get_websocket_untyped


def test_get_websocket_selector_falls_back_to_untyped_path_on_orig_bases_errors(
    monkeypatch: Any,
) -> None:
    module = importlib.reload(fastapi_integration)
    monkeypatch.setattr(module.WebSocket, "__orig_bases__", (), raising=False)

    reloaded = importlib.reload(module)

    assert reloaded.get_websocket is reloaded._get_websocket_untyped


def test_add_request_context_resolves_untyped_request_dependency() -> None:
    class _RequestService:
        def __init__(self, request: Request) -> None:
            self.request = request

    container = Container()
    fastapi_integration.add_request_context(container)
    container.add(_RequestService, scope=Scope.REQUEST, lifetime=Lifetime.SCOPED)

    token = fastapi_integration._connection_context.set(_request_for_scope("/request"))
    try:
        with container.enter_scope() as resolver:
            service = resolver.resolve(_RequestService)
        assert service.request.url.path == "/request"
    finally:
        fastapi_integration._connection_context.reset(token)


def test_add_request_context_resolves_untyped_websocket_dependency() -> None:
    class _WebSocketService:
        def __init__(self, websocket: WebSocket) -> None:
            self.websocket = websocket

    container = Container()
    fastapi_integration.add_request_context(container)
    container.add(_WebSocketService, scope=Scope.REQUEST, lifetime=Lifetime.SCOPED)

    token = fastapi_integration._connection_context.set(_websocket_for_scope("/websocket"))
    try:
        with container.enter_scope() as resolver:
            service = resolver.resolve(_WebSocketService)
        assert service.websocket.url.path == "/websocket"
    finally:
        fastapi_integration._connection_context.reset(token)
