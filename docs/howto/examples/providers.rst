.. meta::
   :description: diwire provider markers example: lazy provider callables for cycle breaking and deferred construction.

Providers
=========

What you'll learn
-----------------

- Break dependency cycles with ``Provider[T]``.
- Defer expensive object construction and keep scope/lifetime behavior intact.

Run locally
-----------

.. code-block:: bash

   uv run python examples/ex_20_providers/01_providers.py

Example
-------

.. literalinclude:: ../../../examples/ex_20_providers/01_providers.py
   :language: python
   :class: diwire-example py-run
