.. meta::
   :description: Function injection in diwire using Annotated[T, Injected()]. Learn how container.resolve() wraps callables and can create per-call scopes.

Function injection
==================

In addition to constructor injection, diwire can inject dependencies into function parameters.

The building blocks are:

- :class:`diwire.Injected` - a marker used inside ``typing.Annotated``
- :meth:`diwire.Container.resolve` - when given a function, returns an injected callable wrapper

Basic injection with ``Injected()``
-----------------------------------

Mark injectable parameters using ``Annotated[T, Injected()]``.
All other parameters remain caller-provided.

See the runnable scripts in :doc:`/howto/examples/function-injection` (Injected marker section).

Per-call scopes for request handlers
------------------------------------

If your function needs scoped services (for example a request-scoped DB session), resolve the function with a scope:

See the runnable scripts in :doc:`/howto/examples/function-injection` (Per-call scope section).

Decorator style
---------------

You can also use ``resolve()`` as a decorator:

.. code-block:: python

   from typing import Annotated
   from diwire import Container, Injected

   container = Container()


   @container.resolve()
   def handler(service: Annotated["Service", Injected()]) -> str:
       return service.run()

For framework integration (FastAPI/Starlette), also see :doc:`container-context` and :doc:`../howto/web/fastapi`.
