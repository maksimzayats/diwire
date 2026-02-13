.. meta::
   :description: Function injection in diwire using Injected[T] and ProviderContext.inject.

Function injection
==================

In addition to constructor injection, diwire can inject dependencies into function parameters.

The building blocks are:

- :class:`diwire.Injected` - a type wrapper used as ``Injected[T]`` to mark injected parameters
- :class:`diwire.FromContext` - a type wrapper used as ``FromContext[T]`` to read per-scope context
- :meth:`diwire.ProviderContext.inject` - a decorator that returns an injected callable wrapper

Basic usage
-----------

Mark injectable parameters using ``Injected[T]``.
All other parameters remain caller-provided.

See the runnable scripts in :doc:`/howto/examples/function-injection` (Injected marker section).

Decorator style
---------------

``ProviderContext.inject`` supports all decorator forms:

- ``@provider_context.inject``
- ``@provider_context.inject()``
- ``@provider_context.inject(scope=Scope.REQUEST, autoregister_dependencies=True)``
- ``@provider_context.inject(scope=Scope.REQUEST, auto_open_scope=False)``

Example:

.. code-block:: python

   from diwire import Container, Injected, Scope, provider_context

   container = Container()


   @provider_context.inject(scope=Scope.REQUEST)
   def handler(service: Injected["Service"]) -> str:
       return service.run()

Behavior notes
--------------

- ``Injected[...]`` and ``FromContext[...]`` parameters are removed from runtime ``__signature__``
- callers can still override injected values by passing explicit keyword arguments
- by default, the wrapper may enter/exit a scope to satisfy scoped dependencies
- to disable implicit scope opening, set ``auto_open_scope=False``

Generated resolver code passes an internal kwarg (``diwire_resolver``) only for inject-wrapped providers.
This is an internal mechanism; user code should not pass it directly unless integrating at a low level.

FromContext in injected callables
---------------------------------

Inject wrappers can resolve ``FromContext[T]`` parameters from scope context values.
Pass context with reserved kwarg ``diwire_context`` when the wrapper opens a new scope.

.. code-block:: python
   :class: diwire-example py-run

   from diwire import Container, FromContext, Scope, provider_context

   container = Container()

   @provider_context.inject(scope=Scope.REQUEST)
   def handler(value: FromContext[int]) -> int:
       return value

   print(handler(diwire_context={int: 7}))
   print(handler(value=8))

If ``diwire_context`` is provided but the wrapper does not open a new scope,
diwire raises ``DIWireInvalidRegistrationError`` with guidance.

Auto-open scopes (default)
--------------------------

Injected callables may open scopes automatically. The wrapper opens a scope only when needed and
closes it at the end of the call.

.. code-block:: python

   from diwire import Container, Injected, Lifetime, Scope, provider_context

   class RequestService:
       pass

   container = Container()
   container.add_concrete(RequestService, provides=RequestService,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )

   @provider_context.inject(scope=Scope.REQUEST)
   def handler(service: Injected[RequestService]) -> RequestService:
       return service

   service = handler()

Naming note
-----------

The API name is ``inject``. Considered alternatives were ``wire``, ``autowire``, ``inject_call``, and ``inject_params``.

For framework integration (FastAPI/Starlette), also see :doc:`provider-context` and :doc:`../howto/web/fastapi`.
