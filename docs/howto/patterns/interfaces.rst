.. meta::
   :description: Programming to interfaces with diwire: bind Protocols/ABCs to concrete implementations and swap them in tests/environments.

Interfaces (Protocol/ABC)
=========================

If your code depends on abstractions (Protocols/ABCs), you must tell diwire what concrete class to build.

Two common ways:

1. ``concrete_class=...``:

   .. code-block:: python

      container.register(Clock, concrete_class=SystemClock)

2. Decorator:

   .. code-block:: python

      @container.register(Clock, lifetime=Lifetime.SINGLETON)
      class SystemClock:
          ...

Example (runnable)
------------------

See the runnable script in :doc:`../examples/patterns` (Interface registration section).
