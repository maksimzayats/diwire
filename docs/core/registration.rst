.. meta::
   :description: How to register services in diwire: classes, factories, instances, decorators, interface/protocol bindings, and service keys.

Registration
============

You can use diwire with almost no registrations (auto-wiring), but real applications still need a few explicit ones:

- configuration objects (singletons)
- interfaces/protocols (bind to a concrete implementation)
- resources (database sessions/clients with cleanup)
- multiple implementations (named components)

Class / factory / instance
--------------------------

The three direct registration forms:

- **Class**: ``container.register(Logger)``
- **Factory**: ``container.register(Database, factory=create_database)``
- **Instance**: ``container.register(Config, instance=Config(...))``

Full runnable example:

See :doc:`/howto/examples/basics` (Registration methods section).

Decorator registration
----------------------

``@container.register`` is a convenience API that works for:

- classes (optionally with an explicit lifetime/scope)
- factory functions (return type inferred from annotations)
- staticmethod factories (same as regular functions)
- interface bindings (``@container.register(Protocol, lifetime=...)``)

Selected patterns (see the full example for more):

See :doc:`/howto/examples/basics` (Decorator registration section).

Interface/protocol binding
--------------------------

You can bind a protocol/ABC to a concrete implementation in two main ways:

1. Decorator:

   .. code-block:: python

      from typing import Protocol
      from diwire import Container, Lifetime


      class Clock(Protocol):
          def now(self) -> str: ...


      container = Container()


      @container.register(Clock, lifetime=Lifetime.SINGLETON)
      class SystemClock:
          ...

2. Direct registration:

   .. code-block:: python

      container.register(Clock, concrete_class=SystemClock, lifetime=Lifetime.SINGLETON)

Re-registering (overrides)
--------------------------

Registrations are replaceable. Calling ``register()`` again with the same key replaces the previous registration.
This is intentionally useful for testing and for swapping implementations by environment.

Next
----

Continue with :doc:`lifetimes` and :doc:`scopes` - these determine how long objects live, and when cleanup happens.
