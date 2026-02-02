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

Built-in integration (recommended)
----------------------------------

The built-in FastAPI integration auto-wraps endpoints that use
``Injected[T]`` parameters. FastAPI only sees request parameters, and diwire
resolves the injected dependencies when the endpoint is called.

1. Configure the container and install the integration (do this before registering routes that
   use ``Injected``):

   .. code-block:: python

      from fastapi import FastAPI

      from diwire import Container
      from diwire.integrations.fastapi import setup_diwire

      app = FastAPI()
      container = Container()
      setup_diwire(app, container=container, scope="request")

2. Define routes normally (no explicit diwire decorator needed):

   .. code-block:: python

      from typing import Annotated

      from diwire import Injected


      @app.get("/health")
      async def health(service: Injected["Service"]) -> dict[str, str]:
          return {"status": service.ok()}

3. Register request-scoped services (``Lifetime.SCOPED``, ``scope="request"``) and any request-specific objects
   (like ``fastapi.Request``) via factories/contextvars.

Router-level control
--------------------

You can also configure a router to use ``DIWireRoute``:

.. code-block:: python

   from diwire import Container, container_context
   from fastapi import APIRouter

   from diwire.integrations.fastapi import DIWireRoute

   container = Container()
   container_context.set_current(container)

   router = APIRouter(route_class=DIWireRoute)

Manual alternatives
-------------------

If you prefer to be explicit (or want to avoid the integration), you can wrap endpoints manually:

.. code-block:: python

   from fastapi import FastAPI

   from diwire import Container

   app = FastAPI()
   container = Container()


   async def handler() -> dict: ...

   app.add_api_route(
       "/path",
       container.resolve(handler, scope="request"),
       methods=["GET"],
   )

Or use decorator-based wrapping:

.. code-block:: python

   from diwire import Container

   container = Container()


   @app.get("/path")
   @container.resolve(scope="request")
   async def handler() -> dict: ...

For larger applications, ``container_context`` can be used to avoid passing the container
everywhere:

.. code-block:: python

   from diwire import container_context

   @app.get("/path")
   @container_context.resolve(scope="request")
   async def handler() -> dict: ...

Runnable examples
-----------------

See :doc:`../examples/fastapi` for three progressively more advanced FastAPI examples:

- built-in integration with ``setup_diwire``
- decorator-based layering
- ``container_context`` + middleware-managed request context
