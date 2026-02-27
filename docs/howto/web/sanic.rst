.. meta::
   :description: How to use diwire with Sanic: request-scoped injection via middleware/signals and contextvars for HTTP and WebSocket handlers.
   :keywords: sanic dependency injection, python dependency injection sanic, request scope dependency injection

Sanic
=====

The Sanic integration provides request-scoped dependency resolution for both HTTP handlers and
websocket handlers.

Minimal setup
-------------

The integration has two parts:

- :func:`diwire.integrations.sanic.install_request_context` wires Sanic request/response middleware
  plus websocket lifecycle signals to store the active request/websocket objects in
  ``contextvars.ContextVar`` values.
- :func:`diwire.integrations.sanic.add_request_context` registers ``Request``/``Websocket``
  providers in your :class:`diwire.Container`.

.. code-block:: python

   from typing import Any

   from sanic import Request, Sanic
   from sanic.response import json

   from diwire import Container, Injected, Lifetime, Scope, resolver_context
   from diwire.integrations.sanic import add_request_context, install_request_context

   app = Sanic("diwire_sanic_minimal")
   install_request_context(app)

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
   async def health(
       request: Request,
       service: Injected[RequestService],
   ):
       _ = request
       return json({"status": service.run()})

Inject request-bound objects (``Request``/``Websocket``)
--------------------------------------------------------

With context installation + container registration in place, you can inject the active
``Request``/``Websocket`` in handlers and services.

.. code-block:: python

   from dataclasses import dataclass
   from typing import Any

   from sanic import Request, Sanic, Websocket

   from diwire import Container, Injected, Lifetime, Scope, resolver_context
   from diwire.integrations.sanic import add_request_context, install_request_context

   app = Sanic("diwire_sanic_request_injection")
   install_request_context(app)

   container = Container()
   add_request_context(container)


   @dataclass
   class RequestPathService:
       request: Request[Any, Any]

       def path(self) -> str:
           return self.request.path


   @dataclass
   class WebsocketIdentityService:
       websocket: Websocket

       def is_same(self, candidate: Websocket) -> bool:
           return self.websocket is candidate


   container.add(
       RequestPathService,
       provides=RequestPathService,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )
   container.add(
       WebsocketIdentityService,
       provides=WebsocketIdentityService,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )


   @app.get("/request/path")
   @resolver_context.inject(scope=Scope.REQUEST)
   async def request_path(
       request: Request,
       resolved_request: Injected[Request[Any, Any]],
       service: Injected[RequestPathService],
   ):
       _ = request
       return {
           "direct_path": resolved_request.path,
           "service_path": service.path(),
       }


   @app.websocket("/websocket/identity")
   @resolver_context.inject(scope=Scope.REQUEST)
   async def websocket_identity(
       request: Request,
       websocket: Websocket,
       resolved_websocket: Injected[Websocket],
       service: Injected[WebsocketIdentityService],
   ) -> None:
       _ = request
       _ = resolved_websocket is websocket
       _ = service.is_same(websocket)

How it works
------------

1. Request middleware stores the current ``Request`` in context.
2. Websocket lifecycle hooks switch context to the active ``Websocket`` while the websocket
   handler runs while preserving the handshake ``Request`` context, then clear both contexts when
   it ends (including exception paths).
3. ``@resolver_context.inject(scope=Scope.REQUEST)`` resolves ``Injected[...]`` parameters from the
   active request scope.

If you forget :func:`diwire.integrations.sanic.install_request_context`, resolving ``Request`` or
``Websocket`` raises :class:`diwire.exceptions.DIWireIntegrationError`.

Testing
-------

- In-process tests: use ``app.asgi_client`` and ensure your app calls
  ``install_request_context(app)`` and ``add_request_context(container)`` during setup.
- End-to-end (Docker Compose): run ``make test-e2e-sanic``.
