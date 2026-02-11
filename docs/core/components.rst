.. meta::
   :description: Named components in diwire: multiple registrations for the same type via Annotated[T, Component(\"name\")].

Components (named registrations)
================================

Use ``Component(\"name\")`` when you want multiple registrations for the same base type.

The key idea is to use ``typing.Annotated`` as the dependency key:

.. code-block:: python

   from typing import Annotated, TypeAlias

   from diwire import Component

   class Cache: ...

   PrimaryCache: TypeAlias = Annotated[Cache, Component("primary")]
   FallbackCache: TypeAlias = Annotated[Cache, Component("fallback")]

You register and resolve using the same ``Annotated[...]`` key.

Runnable example: :doc:`/howto/examples/named-components`.

