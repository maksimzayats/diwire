.. meta::
   :description: diwire lock modes example: LockMode and thread-safety behavior for cached providers.

Lock modes
==========

What you'll learn
-----------------

- How ``lock_mode=\"auto\"`` behaves for cached providers.
- How to override lock behavior at container and provider levels.

Run locally
-----------

.. code-block:: bash

   uv run python examples/ex_11_lock_modes/01_lock_modes.py

Example
-------

.. literalinclude:: ../../../examples/ex_11_lock_modes/01_lock_modes.py
   :language: python
   :class: diwire-example

