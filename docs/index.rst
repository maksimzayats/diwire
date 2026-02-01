.. meta::
   :description: Type-driven dependency injection for Python. Zero dependencies. Auto-wiring from type hints, scoped lifetimes, async resolution, and generator-based cleanup.
   :keywords: dependency injection, python dependency injection, di container, inversion of control, ioc, type hints, fastapi dependency injection

diwire
======

**Type-driven dependency injection for Python. Zero dependencies. Zero boilerplate.**

diwire is a dependency injection container for Python 3.10+ that builds your object graph from type hints alone.
It supports scoped lifetimes, async-first resolution, generator-based cleanup, and open generics.

Installation
------------

.. code-block:: bash

   uv add diwire

.. code-block:: bash

   pip install diwire

Quick start (30 seconds)
------------------------

Define your classes. Resolve the top-level one. diwire figures out the rest.

.. code-block:: python
   :class: py-run

   from dataclasses import dataclass

   from diwire import Container, Lifetime


   @dataclass
   class Database:
       host: str = "localhost"


   @dataclass
   class UserRepository:
       db: Database


   @dataclass
   class UserService:
       repo: UserRepository


   container = Container(autoregister_default_lifetime=Lifetime.TRANSIENT)
   service = container.resolve(UserService)
   print(service.repo.db.host)  # => localhost

What to read next
-----------------

- :doc:`core/index` - the non-optional concepts you will use everywhere
- :doc:`howto/index` - a cookbook of real-world scenarios (frameworks, patterns, testing)
- :doc:`reference/index` - API reference for the public surface area
- :doc:`interactive` - run small snippets in your browser (Pyodide)

.. toctree::
   :hidden:
   :maxdepth: 2
   :caption: Learn

   why-diwire
   core/index
   howto/index
   reference/index

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: Playground

   interactive
