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

Cancelled job cleanup
---------------------

A background job can be cancelled while it waits for input. Give each job
its own request scope. Keep the scope inside the task that uses the resource.
An async-generator provider can then return a borrowed connection in its
``finally`` block when the job stops.

Cancel the task once, then await it. Catch ``asyncio.CancelledError`` outside
the job's scope. In this example, ``release:done`` appears before ``cancelled``.
The event signals that the job has acquired its connection before cancellation.
No timed delay is needed to select that point.

The connection is an in-memory stand-in. Replace ``release()`` with the real
driver's async release operation. Use the async scope on success and failure
too. A scoped connection is reused inside one job; the next job gets a new one.

This example covers one cancellation during work. A second cancellation during
cleanup, a failed release operation, or process termination needs a separate
shutdown policy. Do not assume that a ``finally`` block makes cleanup immune
to these events.

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_18_async/03_cancelled_job_cleanup.py

.. literalinclude:: ../../../examples/ex_18_async/03_cancelled_job_cleanup.py
   :language: python
   :class: diwire-example py-run
