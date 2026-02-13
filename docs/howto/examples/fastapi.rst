.. meta::
   :description: diwire FastAPI example: request-scoped injection via @provider_context.inject(scope=Scope.REQUEST).

FastAPI
=======

What you'll learn
-----------------

- Decorate endpoints with ``@provider_context.inject(scope=Scope.REQUEST)`` for per-request scopes.
- Use scoped generator providers for deterministic request cleanup.

Run locally
-----------

.. code-block:: bash

   uv run python examples/ex_15_fastapi/01_fastapi.py

Example
-------

.. literalinclude:: ../../../examples/ex_15_fastapi/01_fastapi.py
   :language: python
   :class: diwire-example

