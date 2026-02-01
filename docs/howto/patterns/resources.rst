.. meta::
   :description: Managing resources with diwire: generator factories for deterministic cleanup, async generators for async cleanup, and scope-based lifetimes.

Resources (cleanup)
===================

When a dependency needs cleanup (close/dispose/release), register it as a scoped service using a generator factory.

Sync cleanup (generator)
------------------------

See the runnable script in :doc:`../examples/scopes` (Generator factories section).

Async cleanup (async generator)
-------------------------------

See the runnable script in :doc:`../examples/async` (Async generator cleanup section).

Important
---------

Always put cleanup in a ``finally`` block.
Code after ``yield`` is *not* guaranteed to run because closing a generator raises ``GeneratorExit`` at the yield point.
