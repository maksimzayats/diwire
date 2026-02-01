.. meta::
   :description: Unit-of-work pattern with diwire: share a scoped session across repositories/services and commit/rollback at the end of a scope.

Unit of work
============

If you have a transactional boundary (job, command, message, request), model it as a scope.

Typical setup
-------------

- Session/transaction: ``Lifetime.SCOPED``
- Repositories/services: ``Lifetime.TRANSIENT`` (they pull the current session from the scope)

Example (runnable)
------------------

.. literalinclude:: ../../../examples/ex05_patterns/ex02_repository.py
   :language: python

