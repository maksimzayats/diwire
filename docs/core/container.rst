.. meta::
   :description: How the diwire Container resolves dependencies from type hints, how auto-registration works, and what counts as a dependency key.

Container
=========

The :class:`diwire.Container` is responsible for two things:

1. **Registration**: mapping a dependency key (usually a type) to a provider.
2. **Resolution**: creating objects by inspecting type hints and recursively resolving dependencies.

Auto-wiring (default)
---------------------

By default, ``Container()`` recursively auto-registers eligible concrete classes
while resolving and while registering providers.

.. code-block:: python

   from diwire import Container

   container = Container()

Runnable example: :doc:`/howto/examples/quickstart`.

Strict mode (opt-in)
--------------------

Use strict mode when you need full control over registration:

.. code-block:: python

   from diwire import Container, DependencyRegistrationPolicy, MissingPolicy

   container = Container(
       missing_policy=MissingPolicy.ERROR,
       dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
   )

With this configuration, resolving an unregistered dependency raises
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
