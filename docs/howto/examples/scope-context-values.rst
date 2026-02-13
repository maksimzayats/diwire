.. meta::
   :description: diwire scope context values examples: passing context into scopes and consuming values via FromContext[T].

Scope context values
====================

What you'll learn
-----------------

- Pass per-scope values via ``enter_scope(..., context={...})``.
- Resolve context values via ``FromContext[T]`` in providers and injected callables.

Provider from context
---------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_17_scope_context_values/01_provider_from_context.py

.. literalinclude:: ../../../examples/ex_17_scope_context_values/01_provider_from_context.py
   :language: python
   :class: diwire-example py-run

Nested scope inheritance
------------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_17_scope_context_values/02_nested_scope_inheritance.py

.. literalinclude:: ../../../examples/ex_17_scope_context_values/02_nested_scope_inheritance.py
   :language: python
   :class: diwire-example py-run

Injected callable context
-------------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_17_scope_context_values/03_injected_callable_context.py

.. literalinclude:: ../../../examples/ex_17_scope_context_values/03_injected_callable_context.py
   :language: python
   :class: diwire-example py-run

Annotated context keys
----------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_17_scope_context_values/04_annotated_context_keys.py

.. literalinclude:: ../../../examples/ex_17_scope_context_values/04_annotated_context_keys.py
   :language: python
   :class: diwire-example py-run

Context without scope open
--------------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_17_scope_context_values/05_context_without_scope_open.py

.. literalinclude:: ../../../examples/ex_17_scope_context_values/05_context_without_scope_open.py
   :language: python
   :class: diwire-example py-run
