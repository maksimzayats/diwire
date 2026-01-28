"""Basic FastAPI Integration.

This example shows the simplest way to integrate diwire with FastAPI.
It demonstrates:
- Request-scoped service with automatic cleanup
- Manual route registration with container.resolve()
- Service lifecycle management via async generator factory

Use this pattern when you need explicit control over route registration
or when integrating with existing FastAPI applications.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import FastAPI, Request

from diwire import Container, Injected

app = FastAPI()
container = Container()


@dataclass
class Service:
    """A request-scoped service with unique ID."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def greet(self) -> str:
        return f"Hello from Service! (id: {self.id})"


async def get_service():
    """Factory that creates and cleans up Service instances."""
    service = Service()
    print(f"Service {service.id} created")
    try:
        yield service
    finally:
        print("Closing service")


async def handler(request: Request, service: Annotated[Service, Injected()]) -> dict:
    """Handle the request using the injected service."""
    print(f"Service {service.id} handling request")
    return {"message": service.greet(), "request_id": id(request)}


container.register(Service, factory=get_service, scope="request")

app.add_api_route(
    "/greet",
    # Manually resolve the handler with request scope
    # Check next example for decorator-based approach
    container.resolve(handler, scope="request"),
    methods=["GET"],
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
