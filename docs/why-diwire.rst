.. meta::
   :description: Why diwire exists: a typed, type-hint driven dependency injection container for Python with zero runtime dependencies, scopes, async support, and cleanup.
   :keywords: dependency injection python, type driven dependency injection, type hints dependency injection, ioc container python

Why diwire
==========

diwire is built for teams that want dependency injection to feel like *Python with type hints*, not like a framework.

Goals
-----

- **Type-first wiring**: build the object graph from annotations, so you write fewer registrations.
- **Small surface area**: one container, a few primitives (lifetimes, scopes, components), and predictable behavior.
- **Async-first**: `aresolve()` mirrors `resolve()`, and async factories / async cleanup are first-class.
- **Correct cleanup**: resource lifetimes map to scopes via generator/async-generator factories.
- **Zero runtime dependencies**: keep the library easy to adopt in any environment.

What "type-driven" means in practice
------------------------------------

If you can write this:

.. code-block:: python

   from dataclasses import dataclass


   @dataclass
   class Repo:
       ...


   @dataclass
   class Service:
       repo: Repo

...then diwire can resolve ``Service`` by reading its type hints and resolving dependencies recursively.

When you *do* need explicit control, you still have it:

- register interfaces/protocols to concrete implementations
- register instances (singletons) and factories (sync/async/generator)
- pick lifetimes (`TRANSIENT`, `SINGLETON`, `SCOPED`) and scopes by name
- create multiple named registrations via ``Component("name")``
- precompute resolution via ``compile()`` for maximum throughput

If you're new to DI
-------------------

The recommended path is:

1. :doc:`howto/examples/index` (run the tutorial examples in order)
2. :doc:`core/index` (the mental model behind what you just ran)
3. :doc:`howto/index` (frameworks, testing, and real-world patterns)
4. :doc:`reference/index` (API reference)
