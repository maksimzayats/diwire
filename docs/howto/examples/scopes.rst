.. meta::
   :description: diwire scopes example: enter_scope(), scoped lifetimes, and deterministic cleanup.

Scopes & cleanup
================

What you'll learn
-----------------

- Use ``enter_scope()`` to create nested scopes.
- Use ``Lifetime.SCOPED`` for per-scope caching.
- Use generator/async-generator providers for deterministic cleanup.

Run locally
-----------

.. code-block:: bash

   uv run python examples/ex_04_scopes_and_cleanup/01_scopes_and_cleanup.py

Example
-------

.. literalinclude:: ../../../examples/ex_04_scopes_and_cleanup/01_scopes_and_cleanup.py
   :language: python
   :class: diwire-example py-run

