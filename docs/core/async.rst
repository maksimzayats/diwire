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

.. literalinclude:: ../../examples/ex06_async/ex01_basic_async_factory.py
   :language: python

Async cleanup with async generators
-----------------------------------

Use an **async generator** when you need to ``await`` cleanup (closing connections, sessions, etc.).
The ``finally`` block runs when the scope exits.

.. literalinclude:: ../../examples/ex06_async/ex02_async_generator_cleanup.py
   :language: python

Parallel resolution
-------------------

Independent async dependencies are resolved in parallel via ``asyncio.gather()``.

.. literalinclude:: ../../examples/ex06_async/ex05_mixed_and_parallel.py
   :language: python
