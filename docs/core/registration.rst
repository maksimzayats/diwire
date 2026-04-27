.. meta::
   :description: How to register providers in diwire: instances, concrete types, factories, generators/context managers, and protocol bindings.

Registration
============

diwire can auto-wire many graphs with zero registrations, but real applications typically need explicit providers for:

- configuration objects (instances / singletons)
- interfaces / protocols (bind to a concrete implementation)
- resources (sessions/clients with cleanup)
- multiple implementations (named components)

Direct registration APIs
------------------------

Add (concrete types)
^^^^^^^^^^^^^^^^^^^^

Use :meth:`diwire.Container.add` when you want to resolve ``provides`` but construct ``concrete_type``:

.. code-block:: python

   from typing import Protocol

   from diwire import Container


   class Clock(Protocol):
       def now(self) -> str: ...


   class SystemClock:
       def now(self) -> str:
           return "now"


   container = Container()
   container.add(SystemClock, provides=Clock)

Instances
^^^^^^^^^

Use :meth:`diwire.Container.add_instance` to bind an already-created object:

.. code-block:: python

   from diwire import Container

   class Config: ...

   container = Container()
   container.add_instance(Config())

Factories
^^^^^^^^^

Use :meth:`diwire.Container.add_factory` for custom construction logic (sync or async factories are supported):

.. code-block:: python

   from diwire import Container

   class Client: ...

   def build_client() -> Client:
       return Client()

   container = Container()
   container.add_factory(build_client, provides=Client)

Use :meth:`diwire.Container.add_factory_class` when the factory needs constructor-injected state:

.. code-block:: python

   from dataclasses import dataclass

   from diwire import Container, Injected

   class Settings: ...

   class Client:
       def __init__(self, settings: Settings) -> None:
           self.settings = settings

   @dataclass(kw_only=True)
   class ClientFactory:
       settings: Injected[Settings]

       def __call__(self) -> Client:
           return Client(self.settings)

   container = Container()
   container.add_instance(Settings())
   container.add_factory_class(ClientFactory, provides=Client)

Cleanup providers
^^^^^^^^^^^^^^^^^

For deterministic cleanup, use:

- :meth:`diwire.Container.add_generator` for generator/async-generator providers
- :meth:`diwire.Container.add_generator_class` for callable classes whose ``__call__`` yields resources
- :meth:`diwire.Container.add_context_manager` for (async) context manager providers
- :meth:`diwire.Container.add_context_manager_class` for callable classes whose ``__call__`` returns context managers

``add_generator()`` and ``add_generator_class()`` validate registrations by default and require every ``yield`` /
``yield from`` in the provider body to be inside a ``try`` block with a non-empty ``finally``. If you intentionally
want to skip this validation for a specific registration, pass ``require_generator_finally=False``.

See :doc:`/howto/examples/scopes` for a runnable cleanup example.

Re-registering (overrides)
--------------------------

Registrations are replaceable. Registering a provider again for the same key replaces the previous provider. This is
useful for tests and environment-based swapping.

Next
----

Continue with :doc:`lifetimes` and :doc:`scopes` to control caching and cleanup.
