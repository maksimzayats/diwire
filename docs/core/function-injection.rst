.. meta::
   :description: Function injection in diwire using Injected[T] and Container.inject.

Function injection
==================

In addition to constructor injection, diwire can inject dependencies into function parameters.

The building blocks are:

- :class:`diwire.Injected` - a type wrapper used as ``Injected[T]`` to mark injected parameters
- :meth:`diwire.Container.inject` - a decorator that returns an injected callable wrapper

Basic usage
-----------

Mark injectable parameters using ``Injected[T]``.
All other parameters remain caller-provided.

See the runnable scripts in :doc:`/howto/examples/function-injection` (Injected marker section).

Decorator style
---------------

``Container.inject`` supports all decorator forms:

- ``@container.inject``
- ``@container.inject()``
- ``@container.inject(scope=Scope.REQUEST, autoregister_dependencies=True)``

Example:

.. code-block:: python

   from diwire import Container, Injected, Scope

   container = Container()


   @container.inject(scope=Scope.REQUEST)
   def handler(service: Injected["Service"]) -> str:
       return service.run()

Behavior notes
--------------

- injected parameters are removed from runtime ``__signature__``
- callers can still override injected values by passing explicit keyword arguments
- no implicit scope chain opening happens inside the wrapper

Generated resolver code passes an internal kwarg (``__diwire_resolver``) only for inject-wrapped providers.
This is an internal mechanism; user code should not pass it directly unless integrating at a low level.

Naming note
-----------

The API name is ``inject``. Considered alternatives were ``wire``, ``autowire``, ``inject_call``, and ``inject_params``.

For framework integration (FastAPI/Starlette), also see :doc:`container-context` and :doc:`../howto/web/fastapi`.
