.. meta::
   :description: diwire registration methods examples: instance, concrete types, factories, generators, context managers, and explicit dependency mappings.

Registration methods
====================

What you'll learn
-----------------

- Register providers using ``add_instance()``, ``add_concrete()``, and factory variants.
- Pick the registration method that matches a single responsibility.

Add instance
------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_02_registration_methods/01_add_instance.py

.. literalinclude:: ../../../examples/ex_02_registration_methods/01_add_instance.py
   :language: python
   :class: diwire-example py-run

Add concrete
------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_02_registration_methods/02_add_concrete.py

.. literalinclude:: ../../../examples/ex_02_registration_methods/02_add_concrete.py
   :language: python
   :class: diwire-example py-run

Add factory
-----------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_02_registration_methods/03_add_factory.py

.. literalinclude:: ../../../examples/ex_02_registration_methods/03_add_factory.py
   :language: python
   :class: diwire-example py-run

Add generator cleanup
---------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_02_registration_methods/04_add_generator_cleanup.py

.. literalinclude:: ../../../examples/ex_02_registration_methods/04_add_generator_cleanup.py
   :language: python
   :class: diwire-example py-run

Add context manager cleanup
---------------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_02_registration_methods/05_add_context_manager_cleanup.py

.. literalinclude:: ../../../examples/ex_02_registration_methods/05_add_context_manager_cleanup.py
   :language: python
   :class: diwire-example py-run

Explicit dependencies
---------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_02_registration_methods/06_explicit_dependencies.py

.. literalinclude:: ../../../examples/ex_02_registration_methods/06_explicit_dependencies.py
   :language: python
   :class: diwire-example py-run
