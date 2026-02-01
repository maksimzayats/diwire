.. meta::
   :description: container_context in diwire: a context-local global container for framework integration and lazy resolution without passing the Container everywhere.

container_context
=================

Sometimes you can't (or don't want to) pass a :class:`diwire.Container` through every layer of your app.
For those cases, diwire provides :data:`diwire.container_context`: a **context-local** global container built on
``contextvars`` (with a thread-local fallback for threadpool execution).

The idea
--------

- Configure the container at startup.
- Call ``container_context.set_current(container)``.
- Use decorators to resolve injected callables later, without importing the container.

Basic usage
-----------

.. code-block:: python

   from dataclasses import dataclass
   from typing import Annotated

   from diwire import Container, Injected, Lifetime, container_context


   @container_context.register(lifetime=Lifetime.SINGLETON)
   @dataclass
   class Service:
       name: str = "diwire"


   @container_context.resolve()
   def greet(service: Annotated[Service, Injected()]) -> str:
       return f"hello {service.name}"


   container = Container()
   container_context.set_current(container)

   print(greet())  # => hello diwire

Scoped usage
------------

If you pass ``scope=...`` to ``container_context.resolve()``, the wrapper creates a scope per call (same idea as
``container.resolve(func, scope=...)``).

Framework integration
---------------------

``container_context`` is especially useful in web frameworks where:

- handlers might run in different tasks/threads
- you want handler signatures to stay "framework-friendly"

See: :doc:`../howto/web/fastapi`

