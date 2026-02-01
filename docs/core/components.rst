.. meta::
   :description: Named components in diwire: register and resolve multiple implementations of the same interface using typing.Annotated and Component(\"name\").

Named components
================

Sometimes you want **multiple registrations for the same interface**:

- primary vs replica DB
- in-memory cache vs Redis cache
- real service vs stub implementation

Use :class:`diwire.Component` with ``typing.Annotated`` to create distinct keys.

Example
-------

See the runnable script in :doc:`/howto/examples/components` (Named components section).

Notes
-----

- Prefer resolving by the ``Annotated[...]`` type in application code.
- :class:`diwire.service_key.ServiceKey` exists for low-level use, but most projects never need it directly.
