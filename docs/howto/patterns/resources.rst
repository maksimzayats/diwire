.. meta::
   :description: Managing resources with diwire: generator factories for deterministic cleanup, async generators for async cleanup, and scope-based lifetimes.

Resources (cleanup)
===================

When a dependency needs cleanup (close/dispose/release), register it as a scoped service using a generator factory.

Sync cleanup (generator)
------------------------

.. literalinclude:: ../../../examples/ex02_scopes/ex04_generator_factories.py
   :language: python

Async cleanup (async generator)
-------------------------------

.. literalinclude:: ../../../examples/ex06_async/ex02_async_generator_cleanup.py
   :language: python

Important
---------

Always put cleanup in a ``finally`` block.
Code after ``yield`` is *not* guaranteed to run because closing a generator raises ``GeneratorExit`` at the yield point.

