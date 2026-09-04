.. meta::
   :description: How to use diwire with aiohttp: request-scoped injection via middleware and contextvars for HTTP and WebSocket handlers.
   :keywords: aiohttp dependency injection, python dependency injection aiohttp, request scope dependency injection

aiohttp
=======

The aiohttp integration provides request-scoped dependency resolution with the same
``Injected[T]`` ergonomics used in other web integrations.

Minimal setup
-------------

The integration consists of two pieces:

- :func:`diwire.integrations.aiohttp.request_context_middleware` stores the current
  :class:`aiohttp.web.Request` in a ``contextvars.ContextVar`` for the duration of a request.
- :func:`diwire.integrations.aiohttp.add_request_context` registers ``aiohttp.web.Request`` in your
  :class:`diwire.Container`, so services can depend on the active request.

.. code-block:: python

   from aiohttp import web

   from diwire import Container, Injected, Lifetime, Scope, resolver_context
   from diwire.integrations.aiohttp import add_request_context, request_context_middleware

   app = web.Application(middlewares=[request_context_middleware])

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


   @resolver_context.inject(scope=Scope.REQUEST)
   async def health_handler(
       request: web.Request,
       service: Injected[RequestService],
   ) -> web.StreamResponse:
       return web.json_response({"status": service.run()})


   app.add_routes([web.get("/health", health_handler)])

Inject ``web.Request`` in handlers and services
-----------------------------------------------

With middleware + container registration in place, you can inject the active request directly
and into request-scoped services.

.. code-block:: python

   from dataclasses import dataclass

   from aiohttp import web

   from diwire import Container, Injected, Lifetime, Scope, resolver_context
   from diwire.integrations.aiohttp import add_request_context, request_context_middleware

   app = web.Application(middlewares=[request_context_middleware])
   container = Container()
   add_request_context(container)


   @dataclass
   class RequestPathService:
       request: web.Request

       def path(self) -> str:
           return self.request.path


   container.add(
       RequestPathService,
       provides=RequestPathService,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )


   @resolver_context.inject(scope=Scope.REQUEST)
   async def path_handler(
       request: web.Request,
       resolved_request: Injected[web.Request],
       service: Injected[RequestPathService],
   ) -> web.StreamResponse:
       return web.json_response(
           {
               "direct_path": resolved_request.path,
               "service_path": service.path(),
           }
       )


   app.add_routes([web.get("/path", path_handler)])

WebSocket handler pattern
-------------------------

aiohttp WebSocket handlers still receive ``web.Request`` during the HTTP upgrade handshake.
The same ``Injected[web.Request]`` and service injection pattern works there.

.. code-block:: python

   from dataclasses import dataclass

   from aiohttp import WSMsgType, web

   from diwire import Injected, Scope, resolver_context


   @dataclass
   class WebSocketPathService:
       request: web.Request

       def path(self) -> str:
           return self.request.path


   @resolver_context.inject(scope=Scope.REQUEST)
   async def websocket_handler(
       request: web.Request,
       service: Injected[WebSocketPathService],
   ) -> web.StreamResponse:
       ws = web.WebSocketResponse()
       await ws.prepare(request)
       async for message in ws:
           if message.type == WSMsgType.TEXT:
               await ws.send_str(service.path())
               break
       await ws.close()
       return ws

Testing
-------

- In-process tests: use ``aiohttp.test_utils.TestServer`` + ``TestClient`` with app middleware set
  to ``request_context_middleware`` and call ``add_request_context(container)`` in app setup.
- End-to-end (Docker Compose): run ``just test-e2e-aiohttp``.
