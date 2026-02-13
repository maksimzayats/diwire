.. meta::
   :description: Function injection in diwire using Injected[T] and ResolverContext.inject.

Function injection
==================

In addition to constructor injection, diwire can inject dependencies into function parameters.

The building blocks are:

- :class:`diwire.Injected` - a type wrapper used as ``Injected[T]`` to mark injected parameters
- :class:`diwire.FromContext` - a type wrapper used as ``FromContext[T]`` to read per-scope context
- :meth:`diwire.ResolverContext.inject` - a decorator that returns an injected callable wrapper

Basic usage
-----------

Mark injectable parameters using ``Injected[T]``.
All other parameters remain caller-provided.

See the runnable scripts in :doc:`/howto/examples/function-injection` (Injected marker section).

Decorator style
---------------

``ResolverContext.inject`` supports all decorator forms:

- ``@resolver_context.inject``
- ``@resolver_context.inject()``
- ``@resolver_context.inject(scope=Scope.REQUEST, autoregister_dependencies=True)``
- ``@resolver_context.inject(scope=Scope.REQUEST, auto_open_scope=False)``

Example:

.. code-block:: python

   from diwire import Container, Injected, Scope, resolver_context

   container = Container()


   @resolver_context.inject(scope=Scope.REQUEST)
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
One exception is ``Container(..., use_resolver_context=False)`` mode: unbound
``@resolver_context.inject`` calls must pass ``diwire_resolver=...`` explicitly
(or run under another bound resolver context).

FromContext in injected callables
---------------------------------

Inject wrappers can resolve ``FromContext[T]`` parameters from scope context values.
Pass context with reserved kwarg ``diwire_context`` when the wrapper opens a new scope.

.. code-block:: python
   :class: diwire-example py-run

   from diwire import Container, FromContext, Scope, resolver_context

   container = Container()

   @resolver_context.inject(scope=Scope.REQUEST)
   def handler(value: FromContext[int]) -> int:
       return value

   print(handler(diwire_context={int: 7}))
   print(handler(value=8))

If ``diwire_context`` is provided but the wrapper does not open a new scope,
diwire raises ``DIWireInvalidRegistrationError`` with guidance.

Auto-open scopes (default)
--------------------------

Injected callables may open scopes automatically. With ``auto_open_scope=True`` (default), the
wrapper:

- opens a target scope only when entering a deeper scope is needed and valid
- reuses the current resolver when the target scope is already open (no extra scope entry)
- reuses the current resolver when it is already deeper than the target scope, including existing
  scope context values used by ``FromContext[...]``

.. code-block:: python

   from diwire import Container, FromContext, Injected, Lifetime, Scope, resolver_context

   class RequestService:
       pass

   container = Container()
   container.add_concrete(
       RequestService,
       provides=RequestService,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )

   @resolver_context.inject(scope=Scope.REQUEST)
   def use_request_scope(service: Injected[RequestService]) -> RequestService:
       return service

   @resolver_context.inject(scope=Scope.SESSION)
   def read_value(value: FromContext[int]) -> int:
       return value

   with container.enter_scope(Scope.REQUEST) as request_scope:
       service = use_request_scope(diwire_resolver=request_scope)

   with container.enter_scope(Scope.SESSION, context={int: 11}) as session_scope:
       with session_scope.enter_scope(Scope.REQUEST, context={int: 22}) as request_scope:
           value = read_value(diwire_resolver=request_scope)

Naming note
-----------

The API name is ``inject``. Considered alternatives were ``wire``, ``autowire``, ``inject_call``, and ``inject_params``.

For framework integration (FastAPI/Starlette), also see :doc:`resolver-context` and :doc:`../howto/web/fastapi`.
