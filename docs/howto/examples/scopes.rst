.. meta::
   :description: diwire scopes examples: enter_scope(), SCOPED lifetime, nested scopes, and generator factories with cleanup.

Scopes
======

Scope basics
------------

.. literalinclude:: ../../../examples/ex02_scopes/ex01_scope_basics.py
   :language: python

SCOPED lifetime (shared per scope)
-------------------------------------

.. literalinclude:: ../../../examples/ex02_scopes/ex02_scoped_singleton.py
   :language: python

Nested scopes
-------------

.. literalinclude:: ../../../examples/ex02_scopes/ex03_nested_scopes.py
   :language: python

Generator factories (cleanup on scope exit)
-------------------------------------------

.. literalinclude:: ../../../examples/ex02_scopes/ex04_generator_factories.py
   :language: python
