.. meta::
   :description: diwire scope context values example: passing context to scopes and resolving via FromContext[T].

Scope context values
====================

What you'll learn
-----------------

- Pass per-scope values via ``enter_scope(..., context={...})``.
- Resolve context values via ``FromContext[T]`` in providers and injected callables.

Run locally
-----------

.. code-block:: bash

   uv run python examples/ex_17_scope_context_values/01_scope_context_values.py

Example
-------

.. literalinclude:: ../../../examples/ex_17_scope_context_values/01_scope_context_values.py
   :language: python
   :class: diwire-example py-run

