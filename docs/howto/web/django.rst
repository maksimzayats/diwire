.. meta::
   :description: Pattern for using diwire with Django: request-bound dependencies and request scopes via @resolver_context.inject(scope=Scope.REQUEST).

Django
======

There is no Django-specific integration in diwire. The recommended pattern is:

1. Create a global container at startup.
2. Use middleware to store the current ``HttpRequest`` in a ``ContextVar``.
3. Decorate views with ``@resolver_context.inject(scope=Scope.REQUEST)`` to open/close a request scope per call.

Minimal sketch
--------------

.. code-block:: python

   from contextvars import ContextVar

   from django.http import HttpRequest

   from diwire import Container, Injected, Lifetime, Scope

   container = Container()
   request_var: ContextVar[HttpRequest] = ContextVar("request_var")

   container.add_factory(request_var.get, provides=HttpRequest,
       scope=Scope.REQUEST,
   )


   class DiwireRequestVarMiddleware:
       def __init__(self, get_response):
           self.get_response = get_response

       def __call__(self, request: HttpRequest):
           token = request_var.set(request)
           try:
               return self.get_response(request)
           finally:
               request_var.reset(token)


   class Service:
       ...


   container.add(Service, provides=Service,
       lifetime=Lifetime.SCOPED,
       scope=Scope.REQUEST,
   )


   @resolver_context.inject(scope=Scope.REQUEST)
   def view(request: HttpRequest, service: Injected[Service]):
       _ = request
       _ = service
       ...

If you prefer managing scopes manually in middleware, resolve from the active resolver returned by
``enter_scope(...)`` rather than relying on injected wrappers.

