.. meta::
   :description: Scopes in diwire: request-style scoping, per-scope caching, nested scopes, and deterministic cleanup using generator factories.

Scopes & cleanup
================

Scopes give you a way to say: "for this unit of work (request/job), reuse scoped services and clean them up at the end."

Creating a scope
----------------

Use :meth:`diwire.Container.enter_scope` as a context manager:

See the runnable scripts in :doc:`/howto/examples/scopes` (Scope basics section).

Initial app scope
-----------------

By default, ``Container()`` starts with an active app scope (``Scope.APP``).
Calling ``enter_scope()`` creates a nested scope under that app scope.
Close the initial app scope by calling ``container.close()`` or
``container.aclose()``.

Scoped lifetime
---------------

To share an instance *within* a scope, register it as ``Lifetime.SCOPED`` and provide a scope name:

You can use predefined scope names like ``Scope.REQUEST`` (``app``, ``session``, ``request``) or provide any
custom string name.

See the runnable scripts in :doc:`/howto/examples/scopes` (SCOPED lifetime section).

Generator factories (deterministic cleanup)
----------------------------------------------

When you need cleanup (close a session, release a lock, return a connection to a pool), use a generator factory.
diwire will close the generator when the scope exits, running your ``finally`` block.

See the runnable scripts in :doc:`/howto/examples/scopes` (Generator factories section).

Nested scopes
-------------

Scopes can be nested. A nested scope can still access services registered for its parent scopes.

See the runnable scripts in :doc:`/howto/examples/scopes` (Nested scopes section).

Imperative close
----------------

You can also manage scopes imperatively:

.. code-block:: python

   scope = container.enter_scope("request")
   try:
       ...
   finally:
       scope.close()

There are also convenience methods for closing active scopes by name:

- :meth:`diwire.Container.close_scope`
- :meth:`diwire.Container.aclose_scope`
