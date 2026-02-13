.. meta::
   :description: diwire async examples: async factories with aresolve() and async-generator scope cleanup.

Async
=====

What you'll learn
-----------------

- Register an ``async def`` factory and resolve it via ``await container.aresolve(...)``.
- Use an async-generator provider for deterministic async cleanup within a scope.

Async factory + aresolve
------------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_18_async/01_async_factory_aresolve.py

.. literalinclude:: ../../../examples/ex_18_async/01_async_factory_aresolve.py
   :language: python
   :class: diwire-example py-run

Async generator cleanup
-----------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_18_async/02_async_generator_cleanup.py

.. literalinclude:: ../../../examples/ex_18_async/02_async_generator_cleanup.py
   :language: python
   :class: diwire-example py-run
