.. meta::
   :description: Common diwire errors and how to fix them: missing dependencies, circular dependencies, scope mismatches, and async/sync resolution issues.

Errors & debugging
==================

diwire raises library-specific exceptions from :mod:`diwire.exceptions`.
They are designed to be actionable: the message and attributes tell you what was being resolved and why it failed.

Missing dependencies
--------------------

This usually means one of:

- you disabled auto-registration (``Container(autoregister=False)``) and forgot to register something
- a constructor parameter is a primitive (``str``, ``int``, ...) and you didn't register an instance/factory
- you tried to resolve an interface/protocol without binding a concrete implementation

See the runnable scripts in :doc:`/howto/examples/errors` (Missing dependencies section).

Circular dependencies
---------------------

If ``A`` depends on ``B`` and ``B`` depends on ``A``, resolution cannot complete.
diwire detects the cycle and raises :class:`diwire.exceptions.DIWireCircularDependencyError`.

See the runnable scripts in :doc:`/howto/examples/errors` (Circular dependencies section).

Scope mismatch
--------------

Scope-related errors typically happen when:

- you try to resolve a scoped service outside of its scope
- you keep a reference to a scope and use it after it has exited
- you resolve a generator factory when no scope is active (sync or async)

By default, ``Container()`` starts with an active app scope, so generator factories
registered without an explicit scope will use that initial scope and be cleaned up on
``container.close()`` or ``container.aclose()``. If you see a
``DIWireGeneratorFactoryWithoutScopeError`` or
``DIWireAsyncGeneratorFactoryWithoutScopeError``, it usually means you're resolving in
a context where no scope is active.

See the runnable scripts in :doc:`/howto/examples/errors` (Scope mismatch section).

Async in sync context
---------------------

If any dependency is async, use :meth:`diwire.Container.aresolve` (and ``async with`` scopes).
Trying to resolve an async dependency in a sync path raises
:class:`diwire.exceptions.DIWireAsyncDependencyInSyncContextError`.
