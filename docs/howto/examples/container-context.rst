.. meta::
   :description: diwire container_context example: process-global binding and deferred registration replay.

ContainerContext
================

What you'll learn
-----------------

- Use :data:`diwire.container_context` to avoid passing ``Container`` everywhere.
- Bind the active container once via ``container_context.set_current(container)``.

Run locally
-----------

.. code-block:: bash

   uv run python examples/ex_10_container_context/01_container_context.py

Example
-------

.. literalinclude:: ../../../examples/ex_10_container_context/01_container_context.py
   :language: python
   :class: diwire-example py-run

