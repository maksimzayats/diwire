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

Instances
^^^^^^^^^

Use :meth:`diwire.Container.add_instance` to bind an already-created object:

.. code-block:: python

   from diwire import Container

   class Config: ...

   container = Container()
   container.add_instance(Config())

Concrete types
^^^^^^^^^^^^^^

Use :meth:`diwire.Container.add_concrete` when you want to resolve ``provides`` but construct ``concrete_type``:

.. code-block:: python

   from typing import Protocol

   from diwire import Container


   class Clock(Protocol):
       def now(self) -> str: ...


   class SystemClock:
       def now(self) -> str:
           return "now"


   container = Container()
   container.add_concrete(SystemClock, provides=Clock)

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

Cleanup providers
^^^^^^^^^^^^^^^^^

For deterministic cleanup, use:

- :meth:`diwire.Container.add_generator` for generator/async-generator providers
- :meth:`diwire.Container.add_context_manager` for (async) context manager providers

See :doc:`/howto/examples/scopes` for a runnable cleanup example.

Decorator forms
---------------

``add_concrete()``, ``add_factory()``, ``add_generator()``, and ``add_context_manager()``
all support decorator usage:

.. code-block:: python

   from diwire import Container

   container = Container()


   @container.add_factory()
   def build_value() -> int:
       return 1

Re-registering (overrides)
--------------------------

Registrations are replaceable. Registering a provider again for the same key replaces the previous provider. This is
useful for tests and environment-based swapping.

Next
----

Continue with :doc:`lifetimes` and :doc:`scopes` to control caching and cleanup.

