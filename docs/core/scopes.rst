.. meta::
   :description: Scopes in diwire: request-style scoping, per-scope caching, nested scopes, and deterministic cleanup using generator factories.

Scopes & cleanup
================

Scopes give you a way to say: "for this unit of work (request/job), reuse scoped services and clean them up at the end."

Creating a scope
----------------

Use :meth:`diwire.Container.enter_scope` as a context manager:

.. literalinclude:: ../../examples/ex02_scopes/ex01_scope_basics.py
   :language: python

Scoped lifetime
---------------

To share an instance *within* a scope, register it as ``Lifetime.SCOPED`` and provide a scope name:

.. literalinclude:: ../../examples/ex02_scopes/ex02_scoped_singleton.py
   :language: python

Generator factories (deterministic cleanup)
----------------------------------------------

When you need cleanup (close a session, release a lock, return a connection to a pool), use a generator factory.
diwire will close the generator when the scope exits, running your ``finally`` block.

.. literalinclude:: ../../examples/ex02_scopes/ex04_generator_factories.py
   :language: python

Nested scopes
-------------

Scopes can be nested. A nested scope can still access services registered for its parent scopes.

See: ``examples/ex02_scopes/ex03_nested_scopes.py``.

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
