diwire pytest integration
=========================

This integration lets pytest inject dependencies into test functions when parameters are
annotated as ``Annotated[T, Injected()]``. The plugin removes injected parameters from the
pytest signature, resolves them from a DI container, and calls the test with those values.

Quick start
-----------

Enable the plugin in a test module or ``conftest.py``:

.. code-block:: python

    pytest_plugins = ["diwire.integrations.pytest_plugin"]

Then annotate parameters:

.. code-block:: python

    from typing import Annotated
    from diwire.types import Injected

    def test_example(service: Annotated[Service, Injected()]) -> None:
        assert isinstance(service, Service)

Configuration
-------------

Scope for injected values can be configured in four ways (highest priority first):

1. ``@pytest.mark.diwire_scope("my_scope")`` on the test function
2. CLI option: ``--diwire-scope my_scope``
3. ``diwire_scope`` fixture override (per-test module)
4. ``diwire_scope`` ini value (default is ``test_function``)

Example (ini):

.. code-block:: ini

    [tool.pytest.ini_options]
    diwire_scope = "request"

To disable scoping entirely for injection:

.. code-block:: python

    import pytest

    @pytest.fixture()
    def diwire_scope() -> str | None:
        return None

You can also disable scope for a single test:

.. code-block:: python

    import pytest

    @pytest.mark.diwire_scope(None)
    def test_without_scope(service: Annotated[Service, Injected()]) -> None:
        ...

Fixtures
--------

The plugin provides two fixtures you can override:

- ``diwire_container``: the container used for resolving injected dependencies.
- ``diwire_scope``: scope name to use for injected parameters (``None`` disables scoping).

Example override:

.. code-block:: python

    import pytest
    from diwire.container import Container
    from diwire.types import Lifetime

    @pytest.fixture()
    def diwire_container() -> Container:
        container = Container()
        container.register(Service, lifetime=Lifetime.SINGLETON)
        return container

Behavior details
----------------

- Injected parameters are removed from the pytest signature so fixture discovery works.
- Dependencies are resolved right before the test function runs.
- For async tests, dependencies are resolved inside an async wrapper and awaited.
- Explicit keyword arguments passed to the test callable override injected values.

Notes
-----

- The plugin is loaded via ``pytest_plugins``; it is not auto-registered.
- The default scope name is ``test_function``.
