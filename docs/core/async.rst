.. meta::
   :description: Async support in diwire: async factories, async generator cleanup, async scopes, and aresolve().

Async
=====

diwire supports async providers and async resolution.

Async factories
---------------

``add_factory()`` accepts ``async def`` factories. Resolve them with ``await container.aresolve(...)``.

Async cleanup
-------------

``add_generator()`` supports async generators (``async def ...: yield ...``). Cleanup in the ``finally`` block runs
when the owning scope exits.

Runnable example: :doc:`/howto/examples/async`.

Sync vs async resolution
------------------------

If a dependency chain requires an async provider, calling ``resolve()`` raises
:class:`diwire.exceptions.DIWireAsyncDependencyInSyncContextError`. Use ``aresolve()`` for that chain.

Concurrency note
----------------

diwire does not automatically parallelize independent async dependencies. If you want concurrency (for example, multiple
independent I/O calls), use ``asyncio.gather()`` in your application logic.

