.. meta::
   :description: Type-driven dependency injection for Python. Zero runtime dependencies. Compiled resolver, scopes+cleanup, async, open generics, and Injected/FromContext markers.
   :keywords: dependency injection, python dependency injection, di container, inversion of control, ioc, type hints dependency injection

diwire
======

**Type-driven dependency injection for Python. Zero runtime dependencies.**

**Fastest DI library in our published benchmarks.** See :doc:`howto/advanced/performance`.

diwire is a dependency injection container for Python 3.10+ that builds your object graph from type hints.
It supports scopes + deterministic cleanup, async resolution, open generics, and fast steady-state resolution via
compiled resolvers.

Installation
------------

.. code-block:: bash

   uv add diwire

.. code-block:: bash

   pip install diwire

Quick start
-----------

Define your classes. Resolve the top-level one. diwire figures out the rest.

.. code-block:: python
   :class: py-run

   from dataclasses import dataclass, field

   from diwire import Container, DependencyRegistrationPolicy, MissingPolicy


   @dataclass
   class Database:
       host: str = field(default="localhost", init=False)


   @dataclass
   class UserRepository:
       db: Database


   @dataclass
   class UserService:
       repo: UserRepository


   container = Container(
       missing_policy=MissingPolicy.REGISTER_RECURSIVE,
       dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
   )
   service = container.resolve(UserService)
   print(service.repo.db.host)  # => localhost

Why diwire
----------

- **Zero runtime dependencies**: drop it into any project.
- **Compiled resolver**: build fast resolution paths once with ``compile()``.
- **Scopes + cleanup**: per-request caching and deterministic cleanup via generators/async-generators.
- **Open generics**: register ``Box[T]`` once and resolve ``Box[User]`` safely.
- **Function injection**: ``Injected[T]`` and ``FromContext[T]`` markers keep signatures explicit and typed.

Performance
-----------

For reproducible benchmarks and methodology, see :doc:`howto/advanced/performance`.

What to read next
-----------------

- :doc:`howto/examples/index` - runnable scripts sourced from ``examples/``
- :doc:`core/index` - the mental model behind the tutorial
- :doc:`howto/index` - frameworks, testing, and patterns
- :doc:`reference/index` - API reference for the public surface area

.. toctree::
   :hidden:
   :maxdepth: 2
   :caption: Learn

   why-diwire
   howto/examples/index
   core/index
   howto/index
   reference/index
