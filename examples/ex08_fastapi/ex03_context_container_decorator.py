"""Global Container with Context Pattern.

This example shows how to use container_context for larger applications where:
- The container is configured at startup and accessed globally
- Multiple modules need to resolve dependencies without passing the container
- You want middleware to manage request context

When to use this pattern vs ex01/ex02:
- ex01 (basic): Simple apps with explicit route registration
- ex02 (decorator): Apps with layered architecture, container passed explicitly
- ex03 (this): Larger apps where container needs to be accessed from multiple modules

Key concepts:
- container_context.set_current() makes the container globally accessible
- Request objects can be registered as dependencies via ContextVar
- Middleware manages the request lifecycle
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import FastAPI, Request
from fastapi.params import Query

from diwire import Container, Injected, container_context

app = FastAPI()
request_context: ContextVar[Request] = ContextVar("request_context")


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Middleware that stores the current request in context."""
    token = request_context.set(request)
    try:
        return await call_next(request)
    finally:
        request_context.reset(token)


@dataclass
class Service:
    """Request-scoped service that can access the current request."""

    request: Request
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def greet(self, name: str) -> str:
        return f"Hello, {name}! (from Service {self.id})"

    def get_request_id(self) -> int:
        return id(self.request)


async def get_service(request: Request):
    """Factory that receives the current request as a dependency."""
    service = Service(request=request)
    print(f"Service {service.id} created for path {request.url.path}")
    try:
        yield service
    finally:
        print("Closing service")


class Handler:
    """Handler class demonstrating method-based endpoints."""

    @container_context.resolve(scope="request")
    async def handle(
        self,
        name: Annotated[str, Query()],
        service: Annotated[Service, Injected()],
    ) -> dict[str, str | int]:
        print(f"Handler.handle: processing request for {name}")
        return {"message": service.greet(name), "request_id": service.get_request_id()}


def setup_container() -> None:
    """Configure the global container. Call this at app startup."""
    container = Container()
    container_context.set_current(container)

    container.register(Request, factory=request_context.get, scope="request")
    container.register(Service, factory=get_service, scope="request")


@app.get("/greet")
@container_context.resolve(scope="request")
async def greet(
    name: Annotated[str, Query()],
    service: Annotated[Service, Injected()],
) -> dict[str, str | int]:
    """Endpoint using container_context for dependency resolution."""
    print(f"greet: processing request for {name}")
    return {"message": service.greet(name), "request_id": service.get_request_id()}


# Class-based handler route
app.get("/greet/v2")(Handler().handle)


if __name__ == "__main__":
    import uvicorn

    setup_container()
    uvicorn.run(app)
