.. meta::
   :description: Errors in diwire: common exception types, what they mean, and how to debug them.

Errors
======

diwire raises a small set of library-specific exceptions from :mod:`diwire.exceptions`.

Most common errors
------------------

Dependency not registered
^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`diwire.exceptions.DIWireDependencyNotRegisteredError` is raised when you resolve a key that is not registered
and auto-registration is disabled (strict mode).

Use ``Maybe[T]`` when you want missing registrations to resolve as ``None`` instead of raising.

Scope mismatch
^^^^^^^^^^^^^^

:class:`diwire.exceptions.DIWireScopeMismatchError` is raised when resolution requires a scope that is not currently
active (for example, resolving a request-scoped dependency from the root resolver).

Async dependency in sync context
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`diwire.exceptions.DIWireAsyncDependencyInSyncContextError` is raised when you call ``resolve()`` for a graph
that requires async providers. Use ``await aresolve()`` for that graph.

Invalid provider spec / circular dependencies
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`diwire.exceptions.DIWireInvalidProviderSpecError` is raised when the container cannot plan or generate a valid
resolver for the provider graph. Circular dependencies are detected during planning and surface as
``DIWireInvalidProviderSpecError``.

When a graph is circular, prefer refactoring one edge to ``Provider[T]`` or ``AsyncProvider[T]`` so construction is
deferred and resolved later in the same scope. This breaks compile-time cycles while keeping strict registration
validation. Calling the provider from ``__init__`` can still recurse at runtime, so defer the call until after object
construction.

Dependency inference failures
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`diwire.exceptions.DIWireProviderDependencyInferenceError` is raised when diwire cannot infer provider
dependencies from type hints (for example, missing annotations).

ResolverContext not bound
^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`diwire.exceptions.DIWireResolverNotSetError` is raised when :data:`diwire.resolver_context` is used before an
active resolver is bound (or when ``resolver_context.inject`` has no explicit resolver and no fallback container).

Runnable examples
-----------------

See :doc:`/howto/examples/errors`.
