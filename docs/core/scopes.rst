.. meta::
   :description: Scopes in diwire: ordered scope levels, default enter_scope() transitions, per-scope caching, and deterministic cleanup.

Scopes & cleanup
================

Scopes give you a way to say: "for this unit of work (request/job), reuse scoped services and clean them up at the end."

Scope model
-----------

``Scope`` is an *ordered scope tree* implemented as a collection of :class:`diwire.BaseScope` instances.
Each scope has:

- a numeric ``level`` (depth)
- a ``skippable`` flag used for default transitions

The built-in scope collection is available as :data:`diwire.Scope` (an instance, not an enum).

Entering scopes
---------------

Use :meth:`diwire.Container.enter_scope` as a context manager.

``enter_scope()`` (no argument) transitions to the next **non-skippable** scope level.
With the built-in tree this means ``APP -> REQUEST`` by skipping ``SESSION``.

You can also enter an explicit scope level with ``enter_scope(Scope.SESSION)`` or ``enter_scope(Scope.REQUEST)``.

Runnable example: :doc:`/howto/examples/scopes`.

Scoped lifetime
---------------

To cache a provider *within* a scope, register it as ``Lifetime.SCOPED`` and set ``scope=...`` to a
:class:`diwire.BaseScope` value:

.. code-block:: python

   from diwire import Container, Lifetime, Scope

   class RequestSession: ...

   container = Container()
   container.add(RequestSession, provides=RequestSession,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )

Cleanup
-------

For deterministic cleanup, use generator / async-generator providers (or context manager providers). diwire will run
cleanup when the owning scope exits. Use ``add_generator_class()`` or ``add_context_manager_class()`` when setup and
cleanup need a provider class with constructor-injected state.
Generator registrations added via ``add_generator()`` or ``add_generator_class()`` are validated by default and must
place ``yield`` in a ``try/finally`` block. Opt out per registration with ``require_generator_finally=False`` when
intentionally needed.

Runnable example: :doc:`/howto/examples/scopes`.

Task-local values with ContextVar
---------------------------------

For request/task-local data (tenant id, auth claims, request id), use ``contextvars.ContextVar`` and
register a normal provider that reads ``ContextVar.get()``.

Runnable examples: :doc:`/howto/examples/scope-context-values`.
