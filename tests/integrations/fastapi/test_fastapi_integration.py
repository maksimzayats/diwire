from __future__ import annotations

from typing import cast

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from diwire import Container, Injected, container_context
from diwire.integrations.fastapi import DIWireRoute, setup_diwire


class Service:
    def __init__(self) -> None:
        self.value = "ok"


def test_setup_diwire_wraps_registered_routes() -> None:
    app = FastAPI()
    container = Container()
    container.register(Service)

    token = setup_diwire(app, container=container, scope="request")
    try:

        @app.get("/hello")
        async def hello(service: Injected[Service]) -> dict[str, str]:
            return {"value": service.value}

        client = TestClient(app)
        response = client.get("/hello")

        assert response.status_code == 200
        assert response.json() == {"value": "ok"}
    finally:
        if token is not None:
            container_context.reset(token)


def test_diwire_route_class_wraps_router_routes() -> None:
    container = Container()
    container.register(Service)
    token = container_context.set_current(container)
    try:
        router = APIRouter(route_class=DIWireRoute)

        @router.get("/hello")
        async def hello(service: Injected[Service]) -> dict[str, str]:
            return {"value": service.value}

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/hello")

        assert response.status_code == 200
        assert response.json() == {"value": "ok"}
    finally:
        container_context.reset(token)


def test_setup_diwire_without_container_sets_route_class() -> None:
    app = FastAPI()

    token = setup_diwire(app, scope=None)

    assert token is None
    assert issubclass(app.router.route_class, DIWireRoute)
    assert app.router.route_class.diwire_scope is None


def test_setup_diwire_wraps_existing_routes() -> None:
    app = FastAPI()
    container = Container()
    container.register(Service)

    @container_context.resolve(scope="request")
    async def hello_wrapped(service: Injected[Service]) -> dict[str, str]:
        return {"value": service.value}

    app.add_api_route("/hello", hello_wrapped, methods=["GET"])
    route = cast("APIRoute", app.router.routes[-1])
    route.endpoint = hello_wrapped.__wrapped__

    token = setup_diwire(app, container=container, scope="request")
    try:
        updated_route = cast("APIRoute", app.router.routes[-1])

        assert updated_route is not route
        assert updated_route.endpoint is not hello_wrapped.__wrapped__
        assert getattr(updated_route.endpoint, "__diwire_wrapped__", False)

        client = TestClient(app)
        response = client.get("/hello")

        assert response.status_code == 200
        assert response.json() == {"value": "ok"}
    finally:
        if token is not None:
            container_context.reset(token)


def test_setup_diwire_keeps_wrapped_routes() -> None:
    app = FastAPI()
    container = Container()
    container.register(Service)

    @container_context.resolve(scope="request")
    async def hello_wrapped(service: Injected[Service]) -> dict[str, str]:
        return {"value": service.value}

    app.add_api_route("/hello", hello_wrapped, methods=["GET"])
    route = cast("APIRoute", app.router.routes[-1])

    token = setup_diwire(app, container=container, scope="request")
    try:
        updated_route = cast("APIRoute", app.router.routes[-1])

        assert updated_route is route
        assert updated_route.endpoint is hello_wrapped
    finally:
        if token is not None:
            container_context.reset(token)
