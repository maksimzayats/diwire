.. meta::
   :description: How the diwire Container resolves dependencies from type hints, how auto-registration works, and what counts as a dependency key.

Container
=========

The :class:`diwire.Container` is responsible for two things:

1. **Registration**: mapping a dependency key (usually a type) to a provider.
2. **Resolution**: creating objects by inspecting type hints and recursively resolving dependencies.

Strict mode (default)
---------------------

By default, diwire is strict: resolving a dependency that is not registered raises
:class:`diwire.exceptions.DIWireDependencyNotRegisteredError`.

.. code-block:: python

   from diwire import Container

   container = Container()

Runnable example: :doc:`/howto/examples/quickstart`.

Auto-wiring (opt-in)
--------------------

If you want a “zero configuration” experience, opt in to auto-registration:

.. code-block:: python

   from dataclasses import dataclass

   from diwire import Container, DependencyRegistrationPolicy, MissingPolicy


   @dataclass
   class Repo:
       ...


   @dataclass
   class Service:
       repo: Repo


   container = Container(
       missing_policy=MissingPolicy.REGISTER_RECURSIVE,
       dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
   )
   _ = container.resolve(Service)

This preset tells diwire to register classes as they’re encountered during resolution.

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
