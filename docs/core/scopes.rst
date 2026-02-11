.. meta::
   :description: Scopes in diwire: ordered scope levels, default enter_scope() transitions, per-scope caching, and deterministic cleanup.

Scopes & cleanup
================

Scopes give you a way to say: “for this unit of work (request/job), reuse scoped services and clean them up at the end.”

Scope model
-----------

``Scope`` is an *ordered scope tree* implemented as a collection of :class:`diwire.scope.BaseScope` instances.
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
:class:`diwire.scope.BaseScope` value:

.. code-block:: python

   from diwire import Container, Lifetime, Scope

   class RequestSession: ...

   container = Container(autoregister_concrete_types=False)
   container.add_concrete(RequestSession, provides=RequestSession,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )

Cleanup
-------

For deterministic cleanup, use generator / async-generator providers (or context manager providers). diwire will run
cleanup when the owning scope exits.

Runnable example: :doc:`/howto/examples/scopes`.

Scope context values
--------------------

You can attach per-scope context values when entering a scope and resolve them via ``FromContext[T]`` in providers or
in injected callables.

Runnable example: :doc:`/howto/examples/scope-context-values`.

