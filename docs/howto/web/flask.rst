.. meta::
   :description: Pattern for using diwire with Flask/WSGI: create a request scope in before_request/teardown_request and inject services into view functions.

Flask (WSGI)
============

Flask is synchronous and commonly runs view functions in worker threads/processes.
diwire works well in this environment with an explicit per-request scope.

Recommended pattern
-------------------

1. Create a global container at app startup.
2. Enter a ``"request"`` scope in ``before_request`` and close it in ``teardown_request``.
3. Use ``container.resolve()`` (or ``container_context.resolve()``) to inject services into view functions.

Minimal sketch
--------------

.. code-block:: python

   from flask import Flask, g
   from typing import Annotated

   from diwire import Container, Injected, Lifetime

   app = Flask(__name__)
   container = Container()


   @app.before_request
   def _enter_request_scope() -> None:
       g.diwire_scope = container.enter_scope("request")


   @app.teardown_request
   def _exit_request_scope(_exc) -> None:
       scope = getattr(g, "diwire_scope", None)
       if scope is not None:
           scope.close()


   class Service:
       ...


   container.register(Service, lifetime=Lifetime.SCOPED, scope="request")


   @app.get("/health")
   @container.resolve()  # uses the already-active scope from before_request
   def health(service: Annotated[Service, Injected()]) -> dict[str, bool]:
       return {"ok": True}

If you'd rather have the wrapper create the scope per call, pass ``scope="request"`` to ``resolve()``, but the
hook-based approach is usually a better match for Flask apps.

