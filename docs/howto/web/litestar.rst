.. meta::
   :description: How to use diwire with Litestar: request-scoped injection via middleware/contextvars for HTTP and WebSocket handlers.
   :keywords: litestar dependency injection, python dependency injection litestar, request scope dependency injection

Litestar
========

The Litestar integration provides request-scoped dependency resolution with the same
``Injected[T]`` ergonomics used in other web integrations.

Minimal setup
-------------

The integration consists of two pieces:

- :class:`diwire.integrations.litestar.RequestContextMiddleware` stores the current
  :class:`litestar.connection.ASGIConnection` (HTTP request or WebSocket) in a
  ``contextvars.ContextVar`` for the lifetime of the active connection.
- :func:`diwire.integrations.litestar.add_request_context` registers
  :class:`litestar.connection.Request`, :class:`litestar.connection.WebSocket`, and
  :class:`litestar.connection.ASGIConnection` factories in your :class:`diwire.Container`.

.. code-block:: python

   from litestar import Litestar, get

   from diwire import Container, Injected, Lifetime, Scope, resolver_context
   from diwire.integrations.litestar import RequestContextMiddleware, add_request_context

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


   @get("/health")
   @resolver_context.inject(scope=Scope.REQUEST)
   async def health(service: Injected[RequestService]) -> dict[str, str]:
       return {"status": service.run()}


   app = Litestar(
       route_handlers=[health],
       middleware=[RequestContextMiddleware()],
   )

Inject request-bound objects (Request/WebSocket)
------------------------------------------------

Litestar request/connection classes are generic and do not define default type arguments.
For injection-friendly annotations, define local aliases once and reuse them.

.. code-block:: python

   from dataclasses import dataclass
   from typing import TypeAlias

   from litestar import Litestar, get, websocket
   from litestar.connection import Request, WebSocket
   from litestar.datastructures.state import State

   from diwire import Container, Injected, Lifetime, Scope, resolver_context
   from diwire.integrations.litestar import RequestContextMiddleware, add_request_context

   LitestarRequest: TypeAlias = Request[object, object, State]
   LitestarWebSocket: TypeAlias = WebSocket[object, object, State]

   container = Container()
   add_request_context(container)


   @dataclass
   class RequestPathService:
       request: LitestarRequest

       def path(self) -> str:
           return self.request.url.path


   @dataclass
   class WebSocketPathService:
       websocket: LitestarWebSocket

       def path(self) -> str:
           return self.websocket.url.path


   container.add(
       RequestPathService,
       provides=RequestPathService,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )
   container.add(
       WebSocketPathService,
       provides=WebSocketPathService,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )


   @get("/path")
   @resolver_context.inject(scope=Scope.REQUEST)
   async def path_handler(
       request: LitestarRequest,
       resolved_request: Injected[LitestarRequest],
       service: Injected[RequestPathService],
   ) -> dict[str, str]:
       _ = request
       return {
           "direct_path": resolved_request.url.path,
           "service_path": service.path(),
       }


   @websocket("/ws")
   @resolver_context.inject(scope=Scope.REQUEST)
   async def ws_handler(
       socket: LitestarWebSocket,
       service: Injected[WebSocketPathService],
   ) -> None:
       await socket.accept()
       await socket.send_json({"path": service.path()})
       await socket.close()


   app = Litestar(
       route_handlers=[path_handler, ws_handler],
       middleware=[RequestContextMiddleware()],
   )

Testing
-------

- In-process tests: use :class:`litestar.testing.TestClient` with app middleware set to
  ``RequestContextMiddleware()`` and call ``add_request_context(container)``
  during app setup.
- End-to-end (Docker Compose): run ``just test-e2e-litestar``.
