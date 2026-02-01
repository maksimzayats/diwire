.. meta::
   :description: Core concepts in diwire: container resolution, registrations, lifetimes, scopes, cleanup, function injection, components, async, and open generics.

Core concepts
=============

This section is the mental model behind diwire.
If you prefer learning by doing, start with the :doc:`../howto/examples/index` tutorial and use these pages as the
"why it works" reference.

Recommended order
-----------------

1. :doc:`container` - auto-wiring, what gets resolved, and how keys work
2. :doc:`registration` - explicit registration, decorators, and interfaces
3. :doc:`lifetimes` - transient vs singleton vs scoped
4. :doc:`scopes` - request-like scopes and deterministic cleanup
5. :doc:`function-injection` - injecting into functions with ``Injected()``
6. :doc:`components` - multiple implementations via ``Component("name")``
7. :doc:`open-generics` - open generic registrations and type-safe resolution
8. :doc:`async` - async factories, async cleanup, and ``aresolve()``
9. :doc:`container-context` - global context container for framework integration
10. :doc:`compilation` - precomputing the graph for speed
11. :doc:`errors` - common error modes and how to debug them
12. :doc:`integrations` - dataclasses/pydantic/attrs/msgspec notes

.. toctree::
   :maxdepth: 2

   container
   registration
   lifetimes
   scopes
   function-injection
   components
   open-generics
   async
   container-context
   compilation
   errors
   integrations
