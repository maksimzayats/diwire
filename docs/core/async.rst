.. meta::
   :description: Async support in diwire: async factories, async generator cleanup, async scopes, and aresolve() with parallel dependency resolution.

Async
=====

diwire is async-first:

- async factories are supported (auto-detected)
- async generator factories provide deterministic async cleanup
- :meth:`diwire.Container.aresolve` mirrors :meth:`diwire.Container.resolve`

Async factories + ``aresolve()``
---------------------------------

If any dependency in the graph is async, you must resolve the root using ``aresolve()``.

See the runnable scripts in :doc:`/howto/examples/async` (Basic async factory section).

Async cleanup with async generators
-----------------------------------

Use an **async generator** when you need to ``await`` cleanup (closing connections, sessions, etc.).
The ``finally`` block runs when the scope exits.

See the runnable scripts in :doc:`/howto/examples/async` (Async generator cleanup section).

Parallel resolution
-------------------

Independent async dependencies are resolved in parallel via ``asyncio.gather()``.

See the runnable scripts in :doc:`/howto/examples/async` (Mixed sync/async + parallel resolution section).
