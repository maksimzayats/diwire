.. meta::
   :description: Async support in diwire: async factories, async generator cleanup, async scopes, and aresolve().

Async
=====

diwire supports async providers and async resolution.

Async factories
---------------

``add_factory()`` accepts ``async def`` factories. ``add_factory_class()`` accepts callable classes whose ``__call__``
is async. Resolve async dependency chains with ``await container.aresolve(...)``.

Async cleanup
-------------

``add_generator()`` and ``add_generator_class()`` support async generators (``async def ...: yield ...``).
``add_context_manager()`` and ``add_context_manager_class()`` support async context managers. Generator registrations
are validated by default and must place ``yield`` in ``try/finally``. Cleanup in the ``finally`` block, or in the
context manager's ``__aexit__``, runs when the owning scope exits. Use ``require_generator_finally=False`` on a
specific generator registration to opt out when intentional.

Runnable example: :doc:`/howto/examples/async`.

Sync vs async resolution
------------------------

If a dependency chain requires an async provider, calling ``resolve()`` raises
:class:`diwire.exceptions.DIWireAsyncDependencyInSyncContextError`. Use ``aresolve()`` for that chain.

Concurrency note
----------------

diwire does not automatically parallelize independent async dependencies. If you want concurrency (for example, multiple
independent I/O calls), use ``asyncio.gather()`` in your application logic.
