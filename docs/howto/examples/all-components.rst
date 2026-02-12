.. meta::
   :description: diwire All[T] example: resolve base + component implementations into tuple[T, ...].

Resolve all components
======================

What you'll learn
-----------------

- Collect a tuple of implementations with ``All[T]`` (base + named components).
- Preserve deterministic ordering by registration slot.

Run locally
-----------

.. code-block:: bash

   uv run python examples/ex_22_all_components/01_all_components.py

Example
-------

.. literalinclude:: ../../../examples/ex_22_all_components/01_all_components.py
   :language: python
   :class: diwire-example py-run

