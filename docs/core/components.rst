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


Registration shortcut
---------------------

You can register component-qualified bindings without creating a ``TypeAlias``
first by passing ``component=...``:

.. code-block:: python

   from diwire import Component, Container
   from typing import Annotated

   class Cache: ...

   container = Container()
   container.add_instance(Cache(), provides=Cache, component="primary")

   # Runtime key is still Annotated[..., Component(...)]
   primary_cache = container.resolve(Annotated[Cache, Component("primary")])

The same shortcut is available on ``add``, ``add_factory``,
``add_generator``, ``add_context_manager``, and ``decorate``.


Resolve all components
----------------------

Use ``All[T]`` when you want to collect a tuple containing:

- the plain registration for ``T`` (if present), and
- all component registrations keyed as ``Annotated[T, Component(...)]``.

``container.resolve(All[T])`` always returns ``tuple[T, ...]`` and returns an empty tuple ``()``
when nothing matches. Ordering is deterministic by provider slot (registration order; last
override wins).

Runnable example: :doc:`/howto/examples/all-components`.
