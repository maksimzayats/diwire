.. meta::
   :description: diwire Maybe example: explicit optional dependencies without changing Optional[T] strictness.

Maybe
=====

What you'll learn
-----------------

- Use ``Maybe[T]`` as an explicit optional dependency wrapper.
- Get ``None`` for missing registrations while keeping ``T | None`` strict.
- See constructor-default behavior for missing optional dependencies.

Run locally
-----------

.. code-block:: bash

   uv run python examples/ex_23_maybe/01_maybe.py

Example
-------

.. literalinclude:: ../../../examples/ex_23_maybe/01_maybe.py
   :language: python
   :class: diwire-example py-run
