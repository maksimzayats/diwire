.. meta::
   :description: pytest patterns for diwire: container fixtures, using container_context safely with tokens, and cleaning up scopes.

pytest
======

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

