.. meta::
   :description: Why diwire exists: type-driven DI with a small API, deterministic cleanup, and fast steady-state resolution.
   :keywords: dependency injection python, type driven dependency injection, type hints dependency injection, ioc container python

Why diwire
==========

diwire is built for teams that want dependency injection to feel like *Python with type hints*, not like a framework.

The goals
---------

- **Type-first wiring**: dependencies come from annotations, so most graphs require little to no registration code.
- **Small surface area**: one container, a few primitives (lifetimes, scopes, components), and predictable behavior.
- **Correct cleanup**: resource lifetimes map to scopes via generator/async-generator providers.
- **Async support**: ``aresolve()`` mirrors ``resolve()`` and async providers are first-class.
- **Zero runtime dependencies**: easy to adopt in any environment.
- **Fast steady-state**: compiled resolvers reduce overhead on hot paths.

What “type-driven” means in practice
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

...then diwire can resolve ``Service`` by reading type hints and resolving dependencies recursively.

When you need explicit control, you still have it:

- interface/protocol bindings via ``add_concrete(..., provides=...)``
- instances via ``add_instance(...)``
- factories (sync/async/generator/context manager)
- lifetimes (``TRANSIENT``, ``SCOPED``) and scope transitions (root-scoped ``SCOPED`` behaves like a singleton)
- named registrations via ``Component(\"name\")``
- open generics

Benchmarks
----------

See :doc:`howto/advanced/performance` for benchmark methodology, reproducible commands, and results.
