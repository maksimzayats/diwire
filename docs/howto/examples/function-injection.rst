.. meta::
   :description: diwire function injection example: Injected[T] and @resolver_context.inject.

Function injection
==================

What you'll learn
-----------------

- Use ``Injected[T]`` to mark injected parameters.
- Wrap callables with ``@resolver_context.inject(...)``.

Run locally
-----------

.. code-block:: bash

   uv run python examples/ex_06_function_injection/01_function_injection.py
   uv run python examples/ex_06_function_injection/07_auto_open_scope_reuse.py

Example
-------

.. literalinclude:: ../../../examples/ex_06_function_injection/01_function_injection.py
   :language: python
   :class: diwire-example py-run

Focused auto-open scope reuse
-----------------------------

.. literalinclude:: ../../../examples/ex_06_function_injection/07_auto_open_scope_reuse.py
   :language: python
   :class: diwire-example py-run
