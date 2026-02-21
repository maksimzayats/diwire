.. meta::
   :description: diwire annotation normalization examples: non-component Annotated metadata is stripped from dependency keys.

Annotation normalization
========================

What you'll learn
-----------------

- ``Annotated[T, <non-component-meta>]`` resolves the same as ``T``.
- ``Annotated[T, Component(\"name\"), <non-component-meta>]`` resolves the same as
  ``Annotated[T, Component(\"name\")]``.
- ``FromContext[Annotated[T, <non-component-meta>]]`` looks up the normalized context key.

Registration and resolve key normalization
------------------------------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_24_annotation_normalization/01_registration_keys.py

.. literalinclude:: ../../../examples/ex_24_annotation_normalization/01_registration_keys.py
   :language: python
   :class: diwire-example py-run

FromContext key normalization
-----------------------------

Run locally
~~~~~~~~~~~

.. code-block:: bash

   uv run python examples/ex_24_annotation_normalization/02_from_context_keys.py

.. literalinclude:: ../../../examples/ex_24_annotation_normalization/02_from_context_keys.py
   :language: python
   :class: diwire-example py-run
