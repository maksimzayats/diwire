.. meta::
   :description: How the diwire Container resolves dependencies from type hints, how auto-registration works, and what counts as a dependency key.

Container
=========

The :class:`diwire.Container` is responsible for two things:

1. **Registration**: mapping a dependency key (usually a type) to a provider.
2. **Resolution**: creating objects by inspecting type hints and recursively resolving dependencies.

Auto-wiring (default)
---------------------

By default, diwire will auto-register concrete classes as you resolve them. This enables the “zero configuration”
experience:

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
   _ = container.resolve(Service)

Runnable example: :doc:`/howto/examples/quickstart`.

Strict mode (no auto-registration)
----------------------------------

If you want full control, disable auto-registration:

.. code-block:: python

   from diwire import Container

   container = Container(autoregister_concrete_types=False, autoregister_dependencies=False)

In this mode, resolving a dependency that is not registered raises
:class:`diwire.exceptions.DIWireDependencyNotRegisteredError`.

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

