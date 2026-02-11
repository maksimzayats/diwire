.. meta::
   :description: How to use diwire with FastAPI: per-request scopes via @container.inject(scope=Scope.REQUEST) and Injected[T] parameters.
   :keywords: fastapi dependency injection, python dependency injection fastapi, request scope dependency injection

FastAPI
=======

FastAPI already has its own dependency system, but diwire is useful when you want:

- a single, typed object graph shared across your app
- request/job scopes with deterministic cleanup
- constructor injection for your domain/services

Recommended pattern: decorate endpoints
------------------------------------------------

Decorate endpoints with :meth:`diwire.Container.inject` and use ``Injected[T]`` parameters for injected dependencies.
With ``scope=Scope.REQUEST`` (and the default ``auto_open_scope=True``), the wrapper opens a request scope per call and
closes it when the endpoint returns.

.. code-block:: python

   from fastapi import FastAPI

   from diwire import Container, Injected, Lifetime, Scope

   app = FastAPI()
   container = Container(autoregister_concrete_types=False)


   class RequestService:
       def run(self) -> str:
           return "ok"


   container.register_concrete(
       RequestService,
       concrete_type=RequestService,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )


   @app.get("/health")
   @container.inject(scope=Scope.REQUEST)
   def health(service: Injected[RequestService]) -> dict[str, str]:
       return {"status": service.run()}

Decorator order matters: apply ``@container.inject(...)`` *below* the FastAPI decorator so FastAPI sees the injected
wrapper signature (Injected parameters are removed from the public signature).

Runnable example
----------------

See :doc:`../examples/fastapi`.
