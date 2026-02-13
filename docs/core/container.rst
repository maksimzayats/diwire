.. meta::
   :description: How diwire containers resolve dependencies, with strict Container defaults and explicit AutoregisterContainer auto-wiring.

Container
=========

The :class:`diwire.Container` is responsible for two things:

1. **Registration**: mapping a dependency key (usually a type) to a provider.
2. **Resolution**: creating objects by inspecting type hints and recursively resolving dependencies.

Strict Container (default)
--------------------------

:class:`diwire.Container` is strict by default. Dependencies must be registered explicitly:

.. code-block:: python

   from diwire import Container

   container = Container()

In this mode, resolving a dependency that is not registered raises
:class:`diwire.exceptions.DIWireDependencyNotRegisteredError`.

Auto-wiring (explicit opt-in)
-----------------------------

Use :class:`diwire.AutoregisterContainer` when you want the “zero configuration”
experience:

.. code-block:: python

   from dataclasses import dataclass

   from diwire import AutoregisterContainer


   @dataclass
   class Repo:
       ...


   @dataclass
   class Service:
       repo: Repo


   container = AutoregisterContainer()
   _ = container.resolve(Service)

Runnable example: :doc:`/howto/examples/quickstart`.

Dependency keys
---------------

In practice you’ll use these keys:

- **Types**: ``UserService``, ``Repository``, ...
- **Named components** via ``Annotated[T, Component(\"name\")]``.
- **Closed generics** (e.g. ``Box[User]``) when using open-generic registrations.

Avoid “string keys”: they are harder to type-check and harder to discover.

Next
----

Go to :doc:`registration` for the explicit registration APIs, and :doc:`scopes` for scope transitions and cleanup.
