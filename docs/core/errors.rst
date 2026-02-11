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

Dependency inference failures
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`diwire.exceptions.DIWireProviderDependencyInferenceError` is raised when diwire cannot infer provider
dependencies from type hints (for example, missing annotations).

ContainerContext not bound
^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`diwire.exceptions.DIWireContainerNotSetError` is raised when :data:`diwire.container_context` is used before an
active container is bound via ``set_current()``.

Runnable examples
-----------------

See :doc:`/howto/examples/errors`.
