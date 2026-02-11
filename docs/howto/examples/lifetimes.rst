.. meta::
   :description: diwire lifetimes example: TRANSIENT vs SCOPED, including root-scoped singleton behavior.

Lifetimes
=========

What you'll learn
-----------------

- Choose between ``Lifetime.TRANSIENT`` and ``Lifetime.SCOPED``.
- See how root-scoped ``Lifetime.SCOPED`` behaves like a singleton.

Run locally
-----------

.. code-block:: bash

   uv run python examples/ex_03_lifetimes/01_lifetimes.py

Example
-------

.. literalinclude:: ../../../examples/ex_03_lifetimes/01_lifetimes.py
   :language: python
   :class: diwire-example py-run
