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

The plugin uses a ``diwire_container`` fixture. Override it to register fakes and test-specific
configuration. Injected parameters are always resolved from this root container.

.. code-block:: python

   import pytest

   from diwire import Container, Lifetime


   @pytest.fixture()
   def diwire_container() -> Container:
       container = Container(autoregister=False)
       container.register_concrete(
           Service,
           concrete_type=FakeService,
           lifetime=Lifetime.SINGLETON,
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

Using container_context in tests
--------------------------------

If your app uses :data:`diwire.container_context`, set/reset it in a fixture:

.. code-block:: python

   import pytest

   from diwire import Container, container_context


   @pytest.fixture
   def container() -> Container:
       container = Container()
       token = container_context.set_current(container)
       try:
           yield container
       finally:
           container_context.reset(token)

Cleaning up scopes
------------------

Prefer ``with container.enter_scope(...):`` in tests so scope cleanup is deterministic.
If you create scopes imperatively, close them (or call :meth:`diwire.Container.close`) in teardown.
