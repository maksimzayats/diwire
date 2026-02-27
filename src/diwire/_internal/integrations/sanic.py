from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Final

from sanic import Request, Sanic, Websocket
from sanic.response import HTTPResponse
from sanic.signals import Event

from diwire import Container, Lifetime
from diwire.exceptions import DIWireIntegrationError

_request_context: ContextVar[Request[Any, Any] | None] = ContextVar(
    "diwire_sanic_request_context",
    default=None,
)
_websocket_context: ContextVar[Websocket | None] = ContextVar(
    "diwire_sanic_websocket_context",
    default=None,
)

_REQUEST_CONTEXT_ATTR: Final[str] = "__diwire_request_context_handle"
_WEBSOCKET_CONTEXT_ATTR: Final[str] = "__diwire_websocket_context_handle"
_INSTALLED_ATTR: Final[str] = "__diwire_request_context_installed"
_REQUEST_PROVIDER_KEY: Final[Any] = Request[Any, Any]
_WEBSOCKET_PROVIDER_KEY: Final[Any] = Websocket


def get_connection() -> Request | Websocket:
    websocket = _websocket_context.get()
    if websocket is not None:
        return websocket

    request = _request_context.get()
    if request is not None:
        return request

    msg = "Connection context not available. Ensure install_request_context(app) is called."
    raise DIWireIntegrationError(msg)


def get_request() -> Request:
    request = _request_context.get()
    if request is None:
        msg = "Current connection is not HTTP Request."
        raise DIWireIntegrationError(msg)
    return request


def get_websocket() -> Websocket:
    websocket = _websocket_context.get()
    if websocket is None:
        msg = "Current connection is not WebSocket."
        raise DIWireIntegrationError(msg)
    return websocket


def _pop_token(request: Request[Any, Any], attribute: str) -> Token[Any] | None:
    token = getattr(request.ctx, attribute, None)
    if token is None:
        return None
    delattr(request.ctx, attribute)
    return token


def _reset_request_token(request: Request[Any, Any]) -> None:
    token = _pop_token(request, _REQUEST_CONTEXT_ATTR)
    if token is not None:
        _request_context.reset(token)


def _reset_websocket_token(request: Request[Any, Any]) -> None:
    token = _pop_token(request, _WEBSOCKET_CONTEXT_ATTR)
    if token is not None:
        _websocket_context.reset(token)


async def request_context_middleware(request: Request[Any, Any]) -> None:
    token = _request_context.set(request)
    setattr(request.ctx, _REQUEST_CONTEXT_ATTR, token)


async def response_context_middleware(request: Request[Any, Any], _response: HTTPResponse) -> None:
    _reset_request_token(request)


async def _websocket_context_before(request: Request[Any, Any], websocket: Websocket) -> None:
    token = _websocket_context.set(websocket)
    setattr(request.ctx, _WEBSOCKET_CONTEXT_ATTR, token)


async def _websocket_context_after(request: Request[Any, Any], websocket: Websocket) -> None:
    _ = websocket
    _reset_websocket_token(request)
    _reset_request_token(request)


async def _websocket_context_exception(
    request: Request[Any, Any],
    websocket: Websocket,
    exception: Exception,
) -> None:
    _ = websocket
    _ = exception
    _reset_websocket_token(request)
    _reset_request_token(request)


def install_request_context(app: Sanic[Any, Any]) -> None:
    if getattr(app.ctx, _INSTALLED_ATTR, False):
        return

    app.on_request(request_context_middleware)
    app.on_response(response_context_middleware)  # type: ignore[no-untyped-call]
    app.signal(Event.WEBSOCKET_HANDLER_BEFORE)(_websocket_context_before)
    app.signal(Event.WEBSOCKET_HANDLER_AFTER)(_websocket_context_after)
    app.signal(Event.WEBSOCKET_HANDLER_EXCEPTION)(_websocket_context_exception)

    setattr(app.ctx, _INSTALLED_ATTR, True)


def add_request_context(container: Container) -> None:
    container.add_factory(
        get_request,
        provides=_REQUEST_PROVIDER_KEY,
        lifetime=Lifetime.TRANSIENT,
    )
    container.add_factory(
        get_websocket,
        provides=_WEBSOCKET_PROVIDER_KEY,
        lifetime=Lifetime.TRANSIENT,
    )
