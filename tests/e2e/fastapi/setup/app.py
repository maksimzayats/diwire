import uvicorn
from fastapi import FastAPI
from starlette.websockets import WebSocket, WebSocketDisconnect

from diwire import All, Container, Injected, Lifetime, Scope, resolver_context
from diwire.integrations.fastapi import RequestContextMiddleware, add_request_context
from tests.e2e.fastapi.setup.config import FastAPIE2ESettings
from tests.e2e.fastapi.setup.services import (
    AsyncLeafService,
    CachedAsyncResource,
    CachedAsyncService,
    CMService,
    NoneInstanceValue,
    RequestBasedService,
    RequestWithCustomStateService,
    WebSocketBasedService,
    cached_async_counts,
    provide_async_leaf_service,
    provide_cached_async_resource,
    provide_cached_async_service,
)
from tests.e2e.runtime import assert_free_threaded_runtime

app = FastAPI()
app.add_middleware(RequestContextMiddleware)


@app.get("/health")
async def health() -> str:
    return "OK"


@app.get("/services/request-based")
@resolver_context.inject(scope=Scope.REQUEST)
async def request_based_service(service: Injected[RequestBasedService]) -> str:
    return service.work()


@app.get("/services/request-based-with-custom-state")
@resolver_context.inject(scope=Scope.REQUEST)
async def request_based_service_with_custom_state(
    service: Injected[RequestWithCustomStateService],
) -> str:
    return service.work()


@app.websocket("/services/request-based-with-custom-state")
@resolver_context.inject(scope=Scope.SESSION)
async def websocket_request_based_service_with_custom_state(
    ws: WebSocket,
    service: Injected[WebSocketBasedService],
) -> None:
    await ws.accept()
    while True:
        try:
            _data = await ws.receive_text()
        except WebSocketDisconnect:
            break
        await ws.send_text(service.work())


@app.get("/services/cm-service")
@resolver_context.inject(scope=Scope.REQUEST)
async def cm_service(service: Injected[CMService]) -> str:
    return service.work()


@app.get("/services/async-leaf")
@resolver_context.inject(scope=Scope.REQUEST)
async def async_leaf_service(service: Injected[AsyncLeafService]) -> dict[str, str]:
    return {"kind": "async-leaf", "token": service.token}


@app.get("/services/cached-async-leaf")
@resolver_context.inject(scope=Scope.REQUEST)
async def cached_async_leaf_service(
    first: Injected[CachedAsyncService],
    second: Injected[CachedAsyncService],
    resource: Injected[CachedAsyncResource],
) -> dict[str, str | bool]:
    return {"token": first.token, "same": first is second, "resource": resource.token}


@app.get("/services/cached-async-counts")
async def cached_async_state() -> dict[str, int]:
    return dict(cached_async_counts)


@app.get("/services/none-instance")
@resolver_context.inject(scope=Scope.REQUEST)
async def none_instance(value: Injected[NoneInstanceValue]) -> dict[str, bool]:
    collection = await resolver_context.aresolve(All[NoneInstanceValue])
    return {
        "injected": value is None,
        "sync": resolver_context.resolve(NoneInstanceValue) is None,
        "async": await resolver_context.aresolve(NoneInstanceValue) is None,
        "collection": len(collection) == 1 and collection[0] is None,
    }


def main() -> None:
    assert_free_threaded_runtime()
    container = Container()
    container.add_instance(None, provides=NoneInstanceValue)
    add_request_context(container)
    container.add_factory(
        provide_async_leaf_service,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )
    container.add_context_manager(CMService, scope=Scope.REQUEST)
    container.add_factory(
        provide_cached_async_service,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container.add_generator(
        provide_cached_async_resource,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    settings = container.resolve(FastAPIE2ESettings)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
