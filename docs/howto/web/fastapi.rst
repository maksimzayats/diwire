.. meta::
   :description: How to use diwire with FastAPI: per-request scopes, Injected parameters, and container_context for clean endpoint signatures.
   :keywords: fastapi dependency injection, python dependency injection fastapi, request scope dependency injection

FastAPI
=======

FastAPI already has its own dependency system, but diwire is still useful when you want:

- a single, typed object graph shared across your app
- request/job scopes with deterministic cleanup
- constructor injection for your domain/services
- handler signatures that stay friendly for FastAPI (only request parameters are visible)

Recommended pattern
-------------------

1. Configure the container at startup and set it as current:

   .. code-block:: python

      from diwire import Container, container_context

      container = Container()
      container_context.set_current(container)

2. Use a request scope per request (created by the injected wrapper):

   .. code-block:: python

      from typing import Annotated
      from fastapi import FastAPI

      from diwire import Injected, container_context

      app = FastAPI()


      @app.get("/health")
      @container_context.resolve(scope="request")
      async def health(service: Annotated["Service", Injected()]) -> dict[str, str]:
          return {"status": service.ok()}

3. Register request-scoped services (``Lifetime.SCOPED``, ``scope="request"``) and any request-specific objects
   (like ``fastapi.Request``) via factories/contextvars.

Runnable examples
-----------------

See :doc:`../examples/fastapi` for three progressively more advanced FastAPI examples:

- basic integration with explicit container calls
- decorator-based layering
- ``container_context`` + middleware-managed request context
