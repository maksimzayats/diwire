.. meta::
   :description: Scopes in diwire: request-style scoping, per-scope caching, nested scopes, and deterministic cleanup using generator factories.

Scopes & cleanup
================

Scopes give you a way to say: "for this unit of work (request/job), reuse scoped services and clean them up at the end."

Creating a scope
----------------

Use :meth:`diwire.Container.enter_scope` as a context manager:

See the runnable scripts in :doc:`/howto/examples/scopes` (Scope basics section).

Initial app scope
-----------------

By default, ``Container()`` starts with an active app scope (``Scope.APP``).
Calling ``enter_scope()`` creates a nested scope under that app scope.
Close the initial app scope by calling ``container.close()`` or
``container.aclose()``.

Scoped lifetime
---------------

To share an instance *within* a scope, register it as ``Lifetime.SCOPED`` and provide a scope name:

The ``Scope`` enum provides three built-in scope names:

- ``Scope.APP`` (``"app"``) -- application-wide scope (one per container or app lifetime)
- ``Scope.SESSION`` (``"session"``) -- connection or session scope (e.g., websocket or user session)
- ``Scope.REQUEST`` (``"request"``) -- request or job scope (one per request or unit of work)

Scope parameters accept any string, so you can also provide a custom name like ``"tenant"`` or ``"task"``.

See the runnable scripts in :doc:`/howto/examples/scopes` (SCOPED lifetime section).

Generator factories (deterministic cleanup)
----------------------------------------------

When you need cleanup (close a session, release a lock, return a connection to a pool), use a generator factory.
diwire will close the generator when the scope exits, running your ``finally`` block.
If you register a generator factory without specifying a scope, it is attached to the
initial app scope and cleaned up when you call ``container.close()`` or
``container.aclose()``.

See the runnable scripts in :doc:`/howto/examples/scopes` (Generator factories section).

Nested scopes
-------------

Scopes can be nested. A nested scope can still access services registered for its parent scopes.

See the runnable scripts in :doc:`/howto/examples/scopes` (Nested scopes section).

Scope context values
--------------------

You can attach per-scope context values when entering a scope and resolve them via
``FromContext[T]`` in providers or injected callables.

- Context values are visible to the scope where they were provided and all child scopes.
- Child scopes can override parent values by passing the same key again.
- Keys are unwrapped dependency tokens:
  ``FromContext[int]`` uses key ``int``.
  ``FromContext[Annotated[Db, Component("replica")]]`` uses that full ``Annotated`` token.

.. code-block:: python

   from diwire import Container, FromContext, Lifetime, Scope

   class RequestValue:
       def __init__(self, value: int) -> None:
           self.value = value

   def build_request_value(value: FromContext[int]) -> RequestValue:
       return RequestValue(value=value)

   container = Container()
   container.register_factory(
       RequestValue,
       factory=build_request_value,
       scope=Scope.REQUEST,
       lifetime=Lifetime.TRANSIENT,
   )

   with container.enter_scope(Scope.REQUEST, context={int: 123}) as request_scope:
       assert request_scope.resolve(RequestValue).value == 123

Imperative close
----------------

You can also manage scopes imperatively:

.. code-block:: python

   from diwire import Scope

   scope = container.enter_scope(Scope.REQUEST)
   try:
       ...
   finally:
       scope.close()

There are also convenience methods for closing active scopes by name:

- :meth:`diwire.Container.close_scope`
- :meth:`diwire.Container.aclose_scope`
