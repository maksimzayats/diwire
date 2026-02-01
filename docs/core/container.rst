.. meta::
   :description: How the diwire Container resolves dependencies from type hints, how auto-registration works, and what counts as a service key.

Container
=========

The :class:`diwire.Container` is responsible for two things:

1. **Registration**: mapping a "service key" (usually a type) to an instance or a factory.
2. **Resolution**: creating objects by inspecting type hints and recursively resolving dependencies.

Auto-wiring (default)
---------------------

By default, diwire will auto-register concrete classes as you resolve them.
This is what enables the "zero configuration" experience:

.. code-block:: python

   from dataclasses import dataclass

   from diwire import Container


   @dataclass
   class Repo:
       ...


   @dataclass
   class Service:
       repo: Repo


   container = Container()
   service = container.resolve(Service)

When you resolve ``Service``, the container sees it needs ``Repo`` and resolves that too.

Strict mode (no auto-registration)
----------------------------------------

If you want full control, disable auto-registration:

.. code-block:: python

   from diwire import Container

   container = Container(autoregister=False)

In this mode, resolving an unregistered service raises :class:`diwire.exceptions.DIWireServiceNotRegisteredError`.

Service keys
------------

In practice you'll use these keys:

- **Types**: ``container.register(Logger)``, ``container.resolve(Logger)``
- **Annotated components**: ``Annotated[Cache, Component("primary")]`` (see :doc:`components`)

The container also supports registering under other keys (e.g. strings), but using types keeps the API discoverable
and maximizes help from type checkers.

Next
----

Go to :doc:`registration` to learn every explicit registration style (classes, factories, instances, decorators,
interfaces/protocols, and open generics).
