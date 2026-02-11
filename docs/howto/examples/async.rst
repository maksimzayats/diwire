.. meta::
   :description: diwire async example: async factories, aresolve(), and async cleanup with async generators.

Async
=====

What you'll learn
-----------------

- Register an ``async def`` factory and resolve it via ``await container.aresolve(...)``.
- Use an async-generator provider for deterministic async cleanup within a scope.

Run locally
-----------

.. code-block:: bash

   uv run python examples/ex_18_async/01_async.py

Example
-------

.. literalinclude:: ../../../examples/ex_18_async/01_async.py
   :language: python
   :class: diwire-example py-run

