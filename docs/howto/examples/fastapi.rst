.. meta::
   :description: diwire FastAPI examples: basic integration, decorator-based layering, and container_context with middleware-managed request scope.

FastAPI
=======

.. note::
   These examples require ``fastapi`` and are intended to be run locally.
   They are not runnable in the browser (Pyodide).

Basic integration
-----------------

This example shows the simplest way to integrate diwire with FastAPI:

- request-scoped service with automatic cleanup
- manual route registration with ``container.resolve(..., scope="request")``
- service lifecycle management via an async generator factory

.. code-block:: python
   :class: diwire-example

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

Decorator-based layering
------------------------

This example demonstrates a 3-layer architecture:

- Handler (endpoint) -> Service (business logic) -> Repository (data access)

Key points:

- all layers share the same scoped instances within a request
- ``@container.resolve(scope="request")`` integrates cleanly with ``@app.get()``
- dependencies are resolved automatically via type hints

.. code-block:: python
   :class: diwire-example

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

container_context + middleware-managed request context
------------------------------------------------------

This example shows how to use ``container_context`` for larger applications where:

- the container is configured at startup and accessed globally
- multiple modules need to resolve dependencies without passing the container
- middleware manages request context

Key concepts:

- ``container_context.set_current()`` makes the container globally accessible
- a ``ContextVar`` can be used to register request objects as dependencies
- middleware manages the request lifecycle

.. code-block:: python
   :class: diwire-example

   from __future__ import annotations

   import uuid
   from contextvars import ContextVar
   from dataclasses import dataclass, field
   from typing import Annotated

   from fastapi import FastAPI, Request

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


   def setup_container() -> None:
       """Configure the global container. Call this at app startup."""
       container = Container()
       container_context.set_current(container)

       container.register(Request, factory=request_context.get, scope="request")
       container.register(Service, factory=get_service, scope="request")


   @app.get("/greet")
   @container_context.resolve(scope="request")
   async def greet(
       name: str,
       service: Annotated[Service, Injected()],
   ) -> dict[str, str | int]:
       """Endpoint using container_context for dependency resolution."""
       print(f"greet: processing request for {name}")
       return {"message": service.greet(name), "request_id": service.get_request_id()}

Read more
---------

- :doc:`../../core/container-context`
- :doc:`../web/fastapi`
