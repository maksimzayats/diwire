.. meta::
   :description: Pattern for using diwire with Flask/WSGI: request scopes via @resolver_context.inject(scope=Scope.REQUEST) and request-bound dependencies.

Flask (WSGI)
============

Flask is synchronous and commonly runs view functions in worker threads/processes. diwire works well in this
environment with per-request scopes.

Recommended pattern
-------------------

1. Create a global container at app startup.
2. Register request-scoped providers with ``Lifetime.SCOPED`` and ``scope=Scope.REQUEST``.
3. Decorate views with ``@resolver_context.inject(scope=Scope.REQUEST)`` (the wrapper opens/closes a request scope per call).

Minimal sketch
--------------

.. code-block:: python

   from flask import Flask, Request, request

   from diwire import Container, Injected, Lifetime, Scope

   app = Flask(__name__)
   container = Container(autoregister_concrete_types=False)

   container.add_factory(lambda: request, provides=Request, scope=Scope.REQUEST)


   class Service:
       ...


   container.add_concrete(Service, provides=Service,
       lifetime=Lifetime.SCOPED,
       scope=Scope.REQUEST,
   )


   @app.get("/health")
   @resolver_context.inject(scope=Scope.REQUEST)
   def health(service: Injected[Service]) -> dict[str, bool]:
       _ = service
       return {"ok": True}

If you prefer managing scopes manually (for example, in ``before_request``/``teardown_request``), resolve dependencies
from the active resolver returned by ``enter_scope(...)`` rather than relying on injected wrappers.
