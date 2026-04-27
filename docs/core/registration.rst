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

Use :meth:`diwire.Container.add_factory_class` when the provider logic should live in a reusable object. This is useful
when construction needs its own injected collaborators, configuration, caches, or adapters, but you do not want to
register that provider object as the dependency being resolved. The container injects the class constructor, creates the
factory instance, and resolves the value returned by ``instance.__call__()``:

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

Provider functions and provider classes differ only in where dependencies are injected:

.. list-table::
   :header-rows: 1

   * - API
     - Provider shape
     - Injected dependencies
     - Resolved value
   * - ``add_factory(build_client)``
     - Plain callable
     - ``build_client(...)`` parameters
     - ``build_client(...)`` return value
   * - ``add_factory_class(ClientFactory)``
     - Callable class
     - ``ClientFactory(...)`` constructor
     - ``ClientFactory(...).__call__()`` return value

Cleanup providers
^^^^^^^^^^^^^^^^^

For deterministic cleanup, use:

- :meth:`diwire.Container.add_generator` for generator/async-generator providers
- :meth:`diwire.Container.add_generator_class` for callable classes whose ``__call__`` yields resources
- :meth:`diwire.Container.add_context_manager` for (async) context manager providers
- :meth:`diwire.Container.add_context_manager_class` for callable classes whose ``__call__`` returns context managers

The class variants follow the same constructor-then-call pattern as ``add_factory_class()``. Use them when resource
setup needs injected state but the resource lifetime should still be controlled by the resolver scope.

.. code-block:: python

   from collections.abc import Generator
   from contextlib import contextmanager
   from dataclasses import dataclass

   from diwire import Container, Injected, Lifetime, Scope

   class Settings: ...

   class Client:
       def close(self) -> None: ...

   @dataclass(kw_only=True)
   class ClientContextManagerFactory:
       settings: Injected[Settings]

       @contextmanager
       def __call__(self) -> Generator[Client, None, None]:
           client = Client()
           try:
               yield client
           finally:
               client.close()

   container = Container()
   container.add_instance(Settings())
   container.add_context_manager_class(
       ClientContextManagerFactory,
       provides=Client,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )

For ``add_context_manager_class()``, ``__call__`` should return a context manager or async context manager. Decorating
``__call__`` with :func:`contextlib.contextmanager` is one common way to do that. For ``add_generator_class()``,
``__call__`` is the generator or async generator itself and yields the resolved value directly.

.. list-table::
   :header-rows: 1

   * - API
     - Provider shape
     - Cleanup source
   * - ``add_generator(provide_client)``
     - Plain generator or async generator callable
     - ``provide_client(...)`` resumes/closes on scope exit
   * - ``add_generator_class(ClientProvider)``
     - Callable class whose ``__call__`` is a generator or async generator
     - ``ClientProvider(...).__call__()`` resumes/closes on scope exit
   * - ``add_context_manager(provide_client)``
     - Plain callable returning a context manager or async context manager
     - returned context manager exits on scope exit
   * - ``add_context_manager_class(ClientProvider)``
     - Callable class whose ``__call__`` returns a context manager or async context manager
     - context manager returned by ``ClientProvider(...).__call__()`` exits on scope exit

``add_generator()`` and ``add_generator_class()`` validate registrations by default and require every ``yield`` /
``yield from`` in the provider body to be inside a ``try`` block with a non-empty ``finally``. If you intentionally
want to skip this validation for a specific registration, pass ``require_generator_finally=False``.

See :doc:`/howto/examples/scopes` for scope cleanup examples and :doc:`/howto/examples/registration-methods` for
provider class examples.

Re-registering (overrides)
--------------------------

Registrations are replaceable. Registering a provider again for the same key replaces the previous provider. This is
useful for tests and environment-based swapping.

Next
----

Continue with :doc:`lifetimes` and :doc:`scopes` to control caching and cleanup.
