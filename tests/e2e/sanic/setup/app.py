from typing import Any

from sanic import Request, Sanic, Websocket
from sanic.response import HTTPResponse, text

from diwire import Container, Injected, Scope, resolver_context
from diwire.integrations.sanic import add_request_context, install_request_context
from tests.e2e.sanic.setup.config import SanicE2ESettings
from tests.e2e.sanic.setup.services import (
    CMService,
    RequestBasedService,
    WebSocketBasedService,
    latest_cleanup_path,
)

app = Sanic("diwire_sanic_e2e")
install_request_context(app)


@app.get("/health")
async def health(_request: Request) -> HTTPResponse:
    return text("OK")


@app.get("/services/request-based")
@resolver_context.inject(scope=Scope.REQUEST)
async def request_based_service(
    request: Request,
    service: Injected[RequestBasedService],
) -> HTTPResponse:
    _ = request
    return text(service.work())


@app.get("/services/cm-service")
@resolver_context.inject(scope=Scope.REQUEST)
async def cm_service(
    request: Request,
    service: Injected[CMService],
) -> HTTPResponse:
    _ = request
    return text(service.work())


@app.get("/services/cm-service/cleanup")
async def cm_service_cleanup(_request: Request) -> HTTPResponse:
    cleanup_path = latest_cleanup_path()
    return text(f"Cleanup path: {cleanup_path}")


@app.websocket("/services/request-based-websocket")
@resolver_context.inject(scope=Scope.REQUEST)
async def websocket_request_based_service(
    request: Request,
    ws: Websocket,
    service: Injected[WebSocketBasedService],
    resolved_request: Injected[Request[Any, Any]],
    resolved_websocket: Injected[Websocket],
) -> None:
    _ = request
    _data = await ws.recv()
    payload = (
        f"WebSocket path: {resolved_request.path}; "
        f"Direct match: {resolved_websocket is ws}; "
        f"Service match: {service.matches(ws)}"
    )
    await ws.send(payload)


def main() -> None:
    container = Container()
    add_request_context(container)
    container.add_context_manager(CMService, scope=Scope.REQUEST)

    settings = container.resolve(SanicE2ESettings)
    app.run(host=settings.host, port=settings.port, single_process=True, access_log=False)


if __name__ == "__main__":
    main()
