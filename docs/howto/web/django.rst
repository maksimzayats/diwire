.. meta::
   :description: Pattern for using diwire with Django: configure a global container and manage a per-request scope via middleware.

Django
======

There is no Django-specific integration in diwire, but the same scope/middleware pattern applies.

Recommended pattern
-------------------

1. Create a global container at startup (for example in an app config or a module imported on startup).
2. Add a Django middleware that:

   - enters a ``Scope.REQUEST`` scope at the start of the request
   - closes it in a ``finally`` block
   - optionally stores the scope on the request object for manual resolution

3. Use function injection to keep views thin.

Minimal sketch
--------------

.. code-block:: python

   from contextvars import ContextVar
   from typing import Annotated

   from django.http import HttpRequest

   from diwire import Container, Injected, Lifetime, Scope

   container = Container()
   request_var: ContextVar[HttpRequest] = ContextVar("request_var")
   container.register(HttpRequest, factory=request_var.get, scope=Scope.REQUEST)


   class DiwireMiddleware:
       def __init__(self, get_response):
           self.get_response = get_response

       def __call__(self, request):
           token = request_var.set(request)
           scope = container.enter_scope(Scope.REQUEST)
           try:
               request.diwire_scope = scope  # optional: manual resolution from deep in the stack
               return self.get_response(request)
           finally:
               scope.close()
               request_var.reset(token)


   class Service:
       ...


   container.register(Service, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)


   @container.resolve()
   def view(request, service: Injected[Service]):
       ...

The exact wiring depends on whether you're running Django under WSGI or ASGI and how you prefer to structure
application startup.
