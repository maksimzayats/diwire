.. meta::
   :description: Managing resources with diwire: generator factories for deterministic cleanup, async generators for async cleanup, and scope-based lifetimes.

Resources (cleanup)
===================

When a dependency needs cleanup (close/dispose/release), register it as a scoped service using a generator factory.
If you omit a scope, the generator is attached to the initial app scope and cleaned up
when you call ``container.close()`` or ``container.aclose()``.

Sync cleanup (generator)
------------------------

See :doc:`../examples/scopes`.

Async cleanup (async generator)
-------------------------------

See :doc:`../examples/async`.

Important
---------

Always put cleanup in a ``finally`` block.
Code after ``yield`` is *not* guaranteed to run because closing a generator raises ``GeneratorExit`` at the yield point.

For a background job, keep the async scope inside the task. Cancel the task
once and await it so the scope can finish async cleanup before cancellation
reaches the caller. See :doc:`../examples/async` for a runnable job example
and its shutdown limits.
