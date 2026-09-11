.. meta::
   :description: How to use diwire with Flask: request-scoped injection via add_request_context(container) and Injected[T] parameters without middleware.
   :keywords: flask dependency injection, python dependency injection flask, request scope dependency injection

Flask (WSGI)
============

Flask integration uses Flask's built-in request-local context and does not require middleware.
You register request access once with ``add_request_context(container)``, then use
``@resolver_context.inject(scope=Scope.REQUEST)`` on views.

Minimal setup
-------------

The integration consists of two pieces:

- :func:`diwire.integrations.flask.add_request_context` registers ``flask.Request`` in your
  :class:`diwire.Container`.
- :func:`diwire.integrations.flask.get_request` resolves the current request from Flask's
  active request context and raises :class:`diwire.exceptions.DIWireIntegrationError` when used
  outside a request.

.. code-block:: python

   from flask import Flask, Request

   from diwire import Container, Injected, Lifetime, Scope, resolver_context
   from diwire.integrations.flask import add_request_context

   app = Flask(__name__)
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

Inject ``flask.Request`` in handlers and services
-------------------------------------------------

.. code-block:: python

   from dataclasses import dataclass

   from flask import Flask, Request

   from diwire import Container, Injected, Lifetime, Scope, resolver_context
   from diwire.integrations.flask import add_request_context

   app = Flask(__name__)
   container = Container()
   add_request_context(container)


   @dataclass
   class RequestPathService:
       request: Request

       def path(self) -> str:
           return self.request.path


   container.add(
       RequestPathService,
       provides=RequestPathService,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )


   @app.get("/path")
   @resolver_context.inject(scope=Scope.REQUEST)
   def path_handler(
       request: Injected[Request],
       service: Injected[RequestPathService],
   ) -> dict[str, str]:
       return {
           "direct_path": request.path,
           "service_path": service.path(),
       }

How it works
------------

1. Flask opens a request context and exposes ``flask.request`` as a request-local proxy.
2. ``@resolver_context.inject(scope=Scope.REQUEST)`` opens a request scope, resolves
   ``Injected[...]`` parameters, and calls your view.
3. ``add_request_context(container)`` makes ``flask.Request`` resolvable by reading the active
   Flask request proxy.
4. When the view returns, the injected wrapper closes the request scope and runs scoped cleanup.

Testing
-------

- In-process tests: use ``app.test_client()`` and call ``add_request_context(container)`` in app setup.
- End-to-end (Docker Compose): run ``just test-e2e-flask``.
