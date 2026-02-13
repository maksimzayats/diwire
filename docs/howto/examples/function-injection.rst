.. meta::
   :description: diwire function injection examples: Injected[T], resolver_context wrappers, scope behavior, and async details.

Function injection
==================

What you'll learn
-----------------

- Use ``Injected[T]`` to mark injected parameters.
- Wrap callables with ``@resolver_context.inject(...)``.
- Control scope behavior for injected wrappers.

Signature filtering
-------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_06_function_injection/01_signature_filtering.py

.. literalinclude:: ../../../examples/ex_06_function_injection/01_signature_filtering.py
   :language: python
   :class: diwire-example py-run

Override injected values
------------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_06_function_injection/02_override_injected.py

.. literalinclude:: ../../../examples/ex_06_function_injection/02_override_injected.py
   :language: python
   :class: diwire-example py-run

Auto-open scope cleanup
-----------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_06_function_injection/03_auto_open_scope_cleanup.py

.. literalinclude:: ../../../examples/ex_06_function_injection/03_auto_open_scope_cleanup.py
   :language: python
   :class: diwire-example py-run

Nested wrappers
---------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_06_function_injection/04_nested_wrappers.py

.. literalinclude:: ../../../examples/ex_06_function_injection/04_nested_wrappers.py
   :language: python
   :class: diwire-example py-run

Auto-open scope reuse
---------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_06_function_injection/05_auto_open_scope_reuse.py

.. literalinclude:: ../../../examples/ex_06_function_injection/05_auto_open_scope_reuse.py
   :language: python
   :class: diwire-example py-run

Async deep dive
---------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_06_function_injection/06_function_injection_async_details.py

.. literalinclude:: ../../../examples/ex_06_function_injection/06_function_injection_async_details.py
   :language: python
   :class: diwire-example py-run
