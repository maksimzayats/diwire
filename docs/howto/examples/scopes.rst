.. meta::
   :description: diwire scopes examples: enter_scope(), scope mismatch, and deterministic cleanup behavior.

Scopes & cleanup
================

What you'll learn
-----------------

- Use ``enter_scope()`` to create nested scopes.
- Use ``Lifetime.SCOPED`` for per-scope caching.
- Use generator providers for deterministic cleanup.

Scope transitions
-----------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_04_scopes_and_cleanup/01_scope_transitions.py

.. literalinclude:: ../../../examples/ex_04_scopes_and_cleanup/01_scope_transitions.py
   :language: python
   :class: diwire-example py-run

Scope mismatch
--------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_04_scopes_and_cleanup/02_scope_mismatch.py

.. literalinclude:: ../../../examples/ex_04_scopes_and_cleanup/02_scope_mismatch.py
   :language: python
   :class: diwire-example py-run

Scoped cleanup
--------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_04_scopes_and_cleanup/03_scoped_cleanup.py

.. literalinclude:: ../../../examples/ex_04_scopes_and_cleanup/03_scoped_cleanup.py
   :language: python
   :class: diwire-example py-run

Singleton cleanup
-----------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_04_scopes_and_cleanup/04_singleton_cleanup.py

.. literalinclude:: ../../../examples/ex_04_scopes_and_cleanup/04_singleton_cleanup.py
   :language: python
   :class: diwire-example py-run
