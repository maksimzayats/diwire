.. meta::
   :description: diwire autoregistration examples: resolve-time chains, registration-time dependencies, strict mode, and special-case UUID handling.

Autoregistration
================

What you'll learn
-----------------

- How strict ``Container`` and explicit ``AutoregisterContainer`` affect behavior.

Resolve-time chain
------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_09_autoregistration/01_resolve_chain.py

.. literalinclude:: ../../../examples/ex_09_autoregistration/01_resolve_chain.py
   :language: python
   :class: diwire-example py-run

Registration-time dependency autoregistration
---------------------------------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_09_autoregistration/02_add_dependency_autoregister.py

.. literalinclude:: ../../../examples/ex_09_autoregistration/02_add_dependency_autoregister.py
   :language: python
   :class: diwire-example py-run

Strict mode
-----------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_09_autoregistration/03_strict_mode.py

.. literalinclude:: ../../../examples/ex_09_autoregistration/03_strict_mode.py
   :language: python
   :class: diwire-example py-run

UUID special type
-----------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_09_autoregistration/04_uuid_special_type.py

.. literalinclude:: ../../../examples/ex_09_autoregistration/04_uuid_special_type.py
   :language: python
   :class: diwire-example py-run
