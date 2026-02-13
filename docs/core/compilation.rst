.. meta::
   :description: Compilation in diwire: compile() caching, invalidation on registration changes, and hot-path binding in strict mode.

Compilation
===========

``compile()`` builds and caches a root resolver for the current registration graph.

Why compile
-----------

- It removes most reflective work from steady-state resolution.
- It makes repeated ``resolve()`` / ``enter_scope()`` calls faster on hot paths.

Caching and invalidation
------------------------

The compiled resolver is cached on the container.

Any registration mutation (calling ``add_*`` or ``decorate(...)``) invalidates the cached resolver. The next call to ``compile()``,
``resolve()``, ``aresolve()``, or ``enter_scope()`` recompiles as needed.

Strict mode (opt-in) hot-path rebinding
---------------------------------------

In strict mode (opt-in via ``missing_policy=MissingPolicy.ERROR`` and
``dependency_registration_policy=DependencyRegistrationPolicy.IGNORE``), diwire
can bind hot-path container entrypoints directly to the compiled resolver
instance. This avoids container-level indirection for:

- ``resolve()``
- ``aresolve()``
- ``enter_scope()``

Runnable example: :doc:`/howto/examples/compilation`.
