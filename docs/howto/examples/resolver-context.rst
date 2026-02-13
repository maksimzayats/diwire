.. meta::
   :description: diwire resolver_context examples: unbound errors, bound resolution, injection wrappers, and explicit resolver behavior.

ResolverContext
===============

What you'll learn
-----------------

- Use :data:`diwire.resolver_context` to avoid passing ``Container`` everywhere.
- Understand binding behavior and explicit resolver requirements.

Unbound error
-------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_10_resolver_context/01_unbound_error.py

.. literalinclude:: ../../../examples/ex_10_resolver_context/01_unbound_error.py
   :language: python
   :class: diwire-example py-run

Bound resolution
----------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_10_resolver_context/02_bound_resolution.py

.. literalinclude:: ../../../examples/ex_10_resolver_context/02_bound_resolution.py
   :language: python
   :class: diwire-example py-run

Inject wrappers
---------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_10_resolver_context/03_inject_wrappers.py

.. literalinclude:: ../../../examples/ex_10_resolver_context/03_inject_wrappers.py
   :language: python
   :class: diwire-example py-run

use_resolver_context=False
--------------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_10_resolver_context/04_use_resolver_context_false.py

.. literalinclude:: ../../../examples/ex_10_resolver_context/04_use_resolver_context_false.py
   :language: python
   :class: diwire-example py-run
