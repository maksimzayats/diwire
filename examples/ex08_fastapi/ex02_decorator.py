"""Layered Dependencies with Decorator Pattern.

This example demonstrates a 3-layer architecture with diwire and FastAPI:
- Handler (endpoint) -> Service (business logic) -> Repository (data access)

Key points:
- All layers share the same scoped instances within a request
- The @container.resolve(scope="request") decorator integrates cleanly with @app.get()
- Dependencies are resolved automatically via type hints

Use this pattern for typical web applications with layered architecture.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import FastAPI
from fastapi.params import Query

from diwire import Container, Injected

app = FastAPI()
container = Container()


@dataclass
class Repository:
    """Data access layer - simulates database operations."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def find_user(self, name: str) -> dict[str, str]:
        print(f"Repository {self.id}: fetching user {name}")
        return {"name": name, "email": f"{name.lower()}@example.com"}


@dataclass
class Service:
    """Business logic layer - depends on Repository."""

    repo: Repository
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def greet(self, name: str) -> str:
        print(f"Service {self.id}: greeting user {name}")
        user = self.repo.find_user(name)
        return f"Hello, {user['name']}!"


async def get_repository():
    """Factory for Repository with lifecycle logging."""
    repo = Repository()
    print(f"Repository {repo.id} created")
    try:
        yield repo
    finally:
        print(f"Repository {repo.id} closed")


async def get_service(repo: Repository):
    """Factory for Service - receives Repository as dependency."""
    service = Service(repo=repo)
    print(f"Service {service.id} created (using Repository {repo.id})")
    try:
        yield service
    finally:
        print("Closing service")


container.register(Repository, factory=get_repository, scope="request")
container.register(Service, factory=get_service, scope="request")


@app.get("/greet")
@container.resolve(scope="request")
async def greet(
    name: Annotated[str, Query()],
    service: Annotated[Service, Injected()],
) -> dict[str, str]:
    """Endpoint that uses the layered dependencies."""
    print(f"Handler: processing request for {name}")
    message = service.greet(name)
    return {"message": message, "service_id": service.id, "repo_id": service.repo.id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
