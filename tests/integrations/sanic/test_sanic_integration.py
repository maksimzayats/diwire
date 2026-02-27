from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from diwire import Container, Injected, Lifetime, Scope, resolver_context

if TYPE_CHECKING:
    from sanic import Request, Sanic, Websocket
    from sanic.response import HTTPResponse


@dataclass
class _RequestPathService:
    request: Request[Any, Any]

    def path(self) -> str:
        return self.request.path


@dataclass
class _WebSocketIdentityService:
    websocket: Websocket

    def is_same(self, candidate: Websocket) -> bool:
        return self.websocket is candidate


@pytest.fixture()
def app() -> Sanic[Any, Any]:
    pytest.importorskip("sanic")
    pytest.importorskip("sanic_testing")

    from sanic import Request, Sanic, Websocket
    from sanic.response import HTTPResponse, json

    from diwire.integrations.sanic import add_request_context, install_request_context

    # diwire resolves dependencies via runtime type hints; populate module globals so
    # forward references like `Request` and `Websocket` can be evaluated.
    globals()["Request"] = Request
    globals()["Websocket"] = Websocket
    globals()["HTTPResponse"] = HTTPResponse

    container = Container()
    add_request_context(container)
    container.add(
        _RequestPathService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add(
        _WebSocketIdentityService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    app = Sanic("diwire_sanic_integration")
    app.ctx.websocket_events = []
    install_request_context(app)

    @app.get("/request/direct")
    @resolver_context.inject(scope=Scope.REQUEST)
    async def request_direct(
        request: Request,
        resolved_request: Injected[Request[Any, Any]],
    ) -> HTTPResponse:
        return json({"path": resolved_request.path})

    @app.get("/request/service")
    @resolver_context.inject(scope=Scope.REQUEST)
    async def request_service(
        request: Request,
        service: Injected[_RequestPathService],
    ) -> HTTPResponse:
        return json({"path": service.path()})

    @app.websocket("/websocket/direct")
    @resolver_context.inject(scope=Scope.REQUEST)
    async def websocket_direct(
        request: Request,
        websocket: Websocket,
        resolved_request: Injected[Request[Any, Any]],
        resolved_websocket: Injected[Websocket],
    ) -> None:
        app.ctx.websocket_events.append(
            {
                "path": resolved_request.path,
                "same_websocket": resolved_websocket is websocket,
            }
        )

    @app.websocket("/websocket/service")
    @resolver_context.inject(scope=Scope.REQUEST)
    async def websocket_service(
        request: Request,
        websocket: Websocket,
        service: Injected[_WebSocketIdentityService],
    ) -> None:
        app.ctx.websocket_events.append(
            {
                "same_websocket": service.is_same(websocket),
            }
        )

    return app


@pytest.mark.asyncio
async def test_request_resolve_for_http_endpoint(app: Sanic[Any, Any]) -> None:
    _request, response = await app.asgi_client.get("/request/direct")
    assert response.status == 200
    assert response.json == {"path": "/request/direct"}


@pytest.mark.asyncio
async def test_request_resolve_in_service_for_http_endpoint(app: Sanic[Any, Any]) -> None:
    _request, response = await app.asgi_client.get("/request/service")
    assert response.status == 200
    assert response.json == {"path": "/request/service"}


@pytest.mark.asyncio
async def test_websocket_resolve_for_websocket_endpoint(app: Sanic[Any, Any]) -> None:
    _request, response = await app.asgi_client.websocket("/websocket/direct")
    assert response["opened"] is True
    assert app.ctx.websocket_events == [
        {
            "path": "/websocket/direct",
            "same_websocket": True,
        }
    ]


@pytest.mark.asyncio
async def test_websocket_resolve_in_service_for_websocket_endpoint(app: Sanic[Any, Any]) -> None:
    _request, response = await app.asgi_client.websocket("/websocket/service")
    assert response["opened"] is True
    assert app.ctx.websocket_events == [
        {
            "same_websocket": True,
        }
    ]
