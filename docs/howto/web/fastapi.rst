.. meta::
   :description: How to use diwire with FastAPI: per-request scopes via @resolver_context.inject(scope=Scope.REQUEST) and Injected[T] parameters.
   :keywords: fastapi dependency injection, python dependency injection fastapi, request scope dependency injection

FastAPI
=======

FastAPI already has its own dependency system, but diwire is useful when you want:

- a single, typed object graph shared across your app
- request/job scopes with deterministic cleanup
- constructor injection for your domain/services

Minimal setup
-------------

The FastAPI integration consists of two pieces:

- :class:`diwire.integrations.fastapi.RequestContextMiddleware` stores the current connection
  (an HTTP :class:`starlette.requests.Request` or :class:`starlette.websockets.WebSocket`) in a
  ``contextvars.ContextVar``.
- :func:`diwire.integrations.fastapi.add_request_context` registers factories in your
  :class:`diwire.Container` so dependencies can request ``Request``/``WebSocket`` and get the
  current connection for the active request.

The recommended pattern is to decorate endpoints with :meth:`diwire.ResolverContext.inject` and
use ``Injected[T]`` parameters for injected dependencies.

.. code-block:: python

   from fastapi import FastAPI

   from diwire import Container, Injected, Lifetime, Scope, resolver_context
   from diwire.integrations.fastapi import RequestContextMiddleware, add_request_context

   app = FastAPI()
   app.add_middleware(RequestContextMiddleware)

   container = Container()
   add_request_context(container)


   class RequestService:
       def run(self) -> str:
           return "ok"


   container.add(
       RequestService,
       provides=RequestService,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )


   @app.get("/health")
   @resolver_context.inject(scope=Scope.REQUEST)
   def health(service: Injected[RequestService]) -> dict[str, str]:
       return {"status": service.run()}

Decorator order matters: apply ``@resolver_context.inject(...)`` *below* the FastAPI decorator so
FastAPI sees the injected wrapper signature (``Injected[...]`` parameters are removed from the
public signature).

Inject request-bound objects (Request/WebSocket)
------------------------------------------------

With the middleware and ``add_request_context(...)`` in place, you can inject the active request
connection into services, not just into the endpoint.

.. code-block:: python

   from fastapi import FastAPI
   from starlette.requests import Request

   from diwire import Container, Injected, Lifetime, Scope, resolver_context
   from diwire.integrations.fastapi import RequestContextMiddleware, add_request_context

   app = FastAPI()
   app.add_middleware(RequestContextMiddleware)

   container = Container()
   add_request_context(container)


   class RequestPathService:
       def __init__(self, request: Request) -> None:
           self._request = request

       def path(self) -> str:
           return self._request.url.path


   container.add(
       RequestPathService,
       provides=RequestPathService,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )


   @app.get("/path")
   @resolver_context.inject(scope=Scope.REQUEST)
   def path(service: Injected[RequestPathService]) -> dict[str, str]:
       return {"path": service.path()}

For WebSockets, you can inject the active :class:`starlette.websockets.WebSocket` the same way
(into services or directly as an ``Injected[WebSocket]`` parameter).

Custom ``request.state`` typing
-------------------------------

Starlette/FastAPI expose ``request.state`` for per-request storage. The diwire integration supports
typed requests, so you can use a custom state type for stronger typing in services.

.. code-block:: python

   from starlette.datastructures import State
   from starlette.requests import Request


   class CustomState(State):
       pass


   class UsesCustomState:
       def __init__(self, request: Request[CustomState]) -> None:
           self._request = request

       def has_state(self) -> bool:
           _ = self._request.state
           return True

How it works
------------

At a high level, every request goes through these steps:

1. FastAPI receives a request (HTTP or WebSocket).
2. ``RequestContextMiddleware`` captures the current connection object and stores it in a
   ``ContextVar`` for the duration of the request/connection.
3. Your endpoint wrapper created by ``@resolver_context.inject(scope=Scope.REQUEST)`` opens a
   request scope (if needed), resolves ``Injected[...]`` parameters from the container, and calls
   the original endpoint function.
4. When the endpoint returns, the request scope is closed, triggering deterministic cleanup for
   scoped providers (including context managers and generator providers).

If you forget the middleware, resolving ``Request``/``WebSocket`` will raise a
:class:`diwire.exceptions.DIWireIntegrationError` because there is no active connection context.

Testing
-------

- In-process tests: use :class:`fastapi.testclient.TestClient` and make sure your app adds
  ``RequestContextMiddleware`` and calls ``add_request_context(container)`` during setup.
- End-to-end (Docker Compose): run ``just test-e2e-fastapi`` to start a real Uvicorn server in a
  container and run HTTP + WebSocket assertions against it.

Runnable example
----------------

See :doc:`../examples/fastapi`.
