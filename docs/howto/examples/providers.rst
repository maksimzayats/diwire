.. meta::
   :description: diwire provider marker examples: cycle breaking, lazy construction, and lifetime semantics.

Providers
=========

What you'll learn
-----------------

- Break dependency cycles with ``Provider[T]``.
- Defer expensive object construction.
- Observe scoped vs transient behavior through provider calls.

Break cycle provider
--------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_20_providers/01_break_cycle_provider.py

.. literalinclude:: ../../../examples/ex_20_providers/01_break_cycle_provider.py
   :language: python
   :class: diwire-example py-run

Lazy construction provider
--------------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_20_providers/02_lazy_construction_provider.py

.. literalinclude:: ../../../examples/ex_20_providers/02_lazy_construction_provider.py
   :language: python
   :class: diwire-example py-run

Provider lifetime semantics
---------------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_20_providers/03_provider_lifetime_semantics.py

.. literalinclude:: ../../../examples/ex_20_providers/03_provider_lifetime_semantics.py
   :language: python
   :class: diwire-example py-run
