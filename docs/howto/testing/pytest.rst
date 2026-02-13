.. meta::
   :description: pytest integration for diwire: Injected[T] parameter injection via the built-in plugin and root-container resolution with an overridable diwire_container fixture.

pytest
======

Built-in pytest plugin (Injected parameters)
--------------------------------------------

diwire ships with an optional pytest plugin that resolves parameters annotated as
``Injected[T]`` from a container.

Enable it in a test module or ``conftest.py``:

.. code-block:: python

   pytest_plugins = ["diwire.integrations.pytest_plugin"]

Then annotate parameters:

.. code-block:: python

   from diwire import Injected


   def test_example(service: Injected["Service"]) -> None:
       assert service is not None

Customizing the container
^^^^^^^^^^^^^^^^^^^^^^^^^

The plugin requires a ``diwire_container`` fixture override. The built-in fixture intentionally raises
until you define your own container setup. Injected parameters are always resolved from this root container.

.. code-block:: python

   import pytest

   from diwire import Container, Lifetime


   @pytest.fixture()
   def diwire_container() -> Container:
       container = Container()
       container.add_concrete(FakeService, provides=Service,
           lifetime=Lifetime.SCOPED,
       )
       return container

Notes
^^^^^

- The plugin removes injected parameters from pytest's fixture signature so normal fixture discovery
  still works.
- The plugin is loaded via ``pytest_plugins``; it is not auto-registered.

Container fixture
-----------------

.. code-block:: python

   import pytest

   from diwire import Container


   @pytest.fixture
   def container() -> Container:
       # Prefer a fresh container per test.
       return Container()

Using resolver_context in tests
--------------------------------

If your app uses :data:`diwire.resolver_context`, prefer explicit resolver injection in tests.
This avoids ambient resolver state leaks between tests.

.. code-block:: python

   import pytest

   from diwire import Container, Injected, resolver_context


   @pytest.fixture
   def container() -> Container:
       container = Container()
       container.add_instance(Service(), provides=Service)
       return container


   @resolver_context.inject
   def build_service(service: Injected[Service]) -> Service:
       return service


   def test_build_service(container: Container) -> None:
       assert build_service(diwire_resolver=container.compile()) is not None

Cleaning up scopes
------------------

Prefer ``with container.enter_scope(...):`` in tests so scope cleanup is deterministic.
If you create scopes imperatively, close them (or call :meth:`diwire.Container.close`) in teardown.
