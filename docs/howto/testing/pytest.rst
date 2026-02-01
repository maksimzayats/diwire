.. meta::
   :description: pytest integration for diwire: Injected() parameter injection via the built-in plugin, container/scope fixtures, using container_context safely with tokens, and cleaning up scopes.

pytest
======

Built-in pytest plugin (Injected parameters)
--------------------------------------------

diwire ships with an optional pytest plugin that resolves parameters annotated as
``Annotated[T, Injected()]`` from a container.

Enable it in a test module or ``conftest.py``:

.. code-block:: python

   pytest_plugins = ["diwire.integrations.pytest_plugin"]

Then annotate parameters:

.. code-block:: python

   from typing import Annotated

   from diwire import Injected


   def test_example(service: Annotated["Service", Injected()]) -> None:
       assert service is not None

Customizing the container
^^^^^^^^^^^^^^^^^^^^^^^^^

The plugin uses a ``diwire_container`` fixture. Override it to register fakes and test-specific
configuration:

.. code-block:: python

   import pytest

   from diwire import Container, Lifetime


   @pytest.fixture()
   def diwire_container() -> Container:
       container = Container(autoregister=False)
       container.register(Service, concrete_class=FakeService, lifetime=Lifetime.SINGLETON)
       return container

Scopes for injected dependencies
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

By default, injected dependencies are resolved inside ``container.enter_scope("test_function")``.

You can configure the scope name in four ways (highest priority first):

1. ``@pytest.mark.diwire_scope("my_scope")`` (or ``None`` to disable scoping for a single test)
2. CLI option: ``--diwire-scope my_scope``
3. Override the ``diwire_scope`` fixture (per test module / conftest)
4. ``diwire_scope`` ini value (default is ``test_function``)

Example (ini):

.. code-block:: ini

   [tool.pytest.ini_options]
   diwire_scope = "request"

To disable scoping entirely:

.. code-block:: python

   import pytest


   @pytest.fixture()
   def diwire_scope() -> str | None:
       return None

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
