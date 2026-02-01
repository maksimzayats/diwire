.. meta::
   :description: Pattern for using diwire with Starlette/ASGI: request scopes, middleware, and contextvars for request-bound dependencies.

Starlette (and other ASGI frameworks)
=====================================

There is no Starlette-specific integration in diwire (by design), but the pattern is the same as FastAPI:

1. Build a container at startup and make it globally accessible (often via :data:`diwire.container_context`).
2. Create a request scope per incoming request.
3. Put request-bound objects (Request, user, trace id, etc.) into a ``ContextVar`` and register them via factories.

Minimal sketch
--------------

.. code-block:: python

   from contextvars import ContextVar
   from typing import Annotated

   from starlette.applications import Starlette
   from starlette.requests import Request
   from starlette.responses import JSONResponse

   from diwire import Container, Injected, container_context

   request_var: ContextVar[Request] = ContextVar("request_var")
   app = Starlette()


   async def middleware(request: Request, call_next):
       token = request_var.set(request)
       try:
           return await call_next(request)
       finally:
           request_var.reset(token)


   app.middleware("http")(middleware)

   container = Container()
   container_context.set_current(container)

   container.register(Request, factory=request_var.get, scope="request")


   @container_context.resolve(scope="request")
   async def handler(
       request: Request,
       service: Annotated["Service", Injected()],
   ) -> JSONResponse:
       return JSONResponse({"ok": True})

The exact routing API differs between frameworks, but the DI pieces stay the same.

