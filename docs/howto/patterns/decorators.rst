.. meta::
   :description: Use Container.decorate() for explicit cross-cutting wrappers like tracing and caching without rewriting consumers.

Decorators
==========

Use ``Container.decorate(...)`` when you want explicit cross-cutting wrappers
without changing consumer constructors.

DIWire keeps the current binding under an internal alias and rebinds the public
key to the decorator factory. This avoids ``A -> Decorator(A)`` circular
resolution errors.

Tracing Example
---------------

.. code-block:: python

   from typing import Protocol

   from diwire import Container


   class HttpClient(Protocol):
       def get(self, url: str) -> bytes: ...


   class RequestsHttpClient:
       def __init__(self, base_url: str) -> None:
           self.base_url = base_url

       def get(self, url: str) -> bytes:
           return b"ok"


   class Tracer:
       def span(self, name: str):
           class _Span:
               def __enter__(self) -> None:
                   return None

               def __exit__(self, exc_type, exc_value, traceback) -> None:
                   return None

           return _Span()


   class TracedHttpClient:
       def __init__(self, inner: HttpClient, tracer: Tracer) -> None:
           self.inner = inner
           self.tracer = tracer

       def get(self, url: str) -> bytes:
           with self.tracer.span("http.get"):
               return self.inner.get(url)


   container = Container()
   container.add_instance("https://api.example.com", provides=str)
   container.add(RequestsHttpClient, provides=HttpClient)
   container.add_instance(Tracer(), provides=Tracer)
   container.decorate(provides=HttpClient, decorator=TracedHttpClient)

Caching Example
---------------

.. code-block:: python

   class Repo:
       ...


   class SqlRepo(Repo):
       ...


   class CachedRepo(Repo):
       def __init__(self, inner: Repo) -> None:
           self.inner = inner


   container.add(SqlRepo, provides=Repo)
   container.decorate(provides=Repo, decorator=CachedRepo)

Decorator Rules
---------------

- ``decorate(...)`` can run before or after the base registration.
- Multiple decorators stack in call order: last ``decorate(...)`` call is
  outermost.
- Re-registering the same ``provides`` key replaces the base and rebuilds the
  decoration chain.
- For ambiguous inner-parameter inference, pass
  ``inner_parameter=\"<parameter_name>\"`` explicitly.

This is explicit provider decoration, not method interception/AOP pointcuts.
