.. meta::
   :description: Performance tuning with diwire: compilation, lifetimes, avoiding reflection on hot paths, and practical throughput tips.

Performance
===========

diwire is designed to be fast by default, but there are a few knobs if you're optimizing a hot path.

Use compilation
---------------

See :doc:`../../core/compilation`.

In short:

- leave ``auto_compile=True`` (default) unless you need manual control
- or call ``container.compile()`` after all registrations

Prefer stable lifetimes for heavy dependencies
----------------------------------------------

- Make heavy clients singletons (HTTP clients, connection pools).
- Make per-request resources scoped (DB sessions, unit-of-work).
- Keep transient graphs lightweight.

Avoid unnecessary work inside factories
---------------------------------------

If a factory does expensive setup, consider:

- turning it into a singleton
- moving expensive work to app startup
- using an async factory and resolving via ``aresolve()``

