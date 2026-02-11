.. meta::
   :description: Lifetimes in diwire: TRANSIENT vs SCOPED, default_lifetime, and how lifetime affects caching and cleanup.

Lifetimes
=========

Lifetimes control when providers are called and whether results are cached.

The built-in lifetimes are:

- ``Lifetime.TRANSIENT``: provider runs on every resolution (no caching)
- ``Lifetime.SCOPED``: cached per active scope (e.g. request)

Root-scoped ``SCOPED`` behaves like a singleton
-----------------------------------------------

When a provider uses ``Lifetime.SCOPED`` with the container root scope (for example ``Scope.APP``),
the value is cached for the lifetime of the container.

Default lifetime
----------------

``Container(default_lifetime=...)`` controls the lifetime used when a registration does not specify one.
The default is ``Lifetime.SCOPED``.

Runnable example: :doc:`/howto/examples/lifetimes`.

When to use what
----------------

- Use root-scoped **SCOPED** for heavy clients (HTTP clients, connection pools).
- Use **SCOPED** for per-request/per-job resources (DB session, unit-of-work).
- Use **TRANSIENT** for lightweight value objects.

Cleanup and lifetimes
---------------------

Cleanup providers (generators/context managers) run their cleanup when the owning cache scope closes:

- ``SCOPED`` cleanup runs when its owning scope closes (``with container.enter_scope(...):``)
- Root-scoped ``SCOPED`` cleanup runs when you close the container
  (``container.close()`` / ``await container.aclose()``)

Runnable example: :doc:`/howto/examples/scopes`.
