.. meta::
   :description: Pattern for using diwire with Starlette/ASGI: request scopes, @resolver_context.inject, and contextvars for request-bound dependencies.

Starlette (and other ASGI frameworks)
=====================================

There is no Starlette-specific integration in diwire (by design). The recommended pattern is:

1. Build a container at startup.
2. Use ``@resolver_context.inject(scope=Scope.REQUEST)`` for request handlers.
3. Use ``contextvars`` only for request-bound objects (``Request``, user, trace id, ...), not for “current container”.

Minimal sketch
--------------

.. code-block:: python

   from contextvars import ContextVar

   from starlette.applications import Starlette
   from starlette.middleware import Middleware
   from starlette.middleware.base import BaseHTTPMiddleware
   from starlette.requests import Request
   from starlette.responses import JSONResponse

   from diwire import Container, Injected, Scope, resolver_context

   request_var: ContextVar[Request] = ContextVar("request_var")


   class RequestVarMiddleware(BaseHTTPMiddleware):
       async def dispatch(self, request: Request, call_next):
           token = request_var.set(request)
           try:
               return await call_next(request)
           finally:
               request_var.reset(token)


   app = Starlette(middleware=[Middleware(RequestVarMiddleware)])
   container = Container()

   container.add_factory(
       lambda: request_var.get(),
       provides=Request,
       scope=Scope.REQUEST,
   )


   class Service:
       ...


   container.add(Service, provides=Service, scope=Scope.REQUEST)


   @resolver_context.inject(scope=Scope.REQUEST)
   async def handler(request: Request, service: Injected[Service]) -> JSONResponse:
       _ = request
       _ = service
       return JSONResponse({"ok": True})

The exact routing API differs between ASGI frameworks, but the DI pieces stay the same.
