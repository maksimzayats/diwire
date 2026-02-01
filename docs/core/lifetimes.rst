.. meta::
   :description: diwire lifetimes: transient, singleton, and scoped. Learn how instance sharing works in a typed dependency injection container.

Lifetimes
=========

Lifetimes control **how often** diwire creates an object.

diwire supports three lifetimes:

- ``Lifetime.TRANSIENT``: create a new instance every time
- ``Lifetime.SINGLETON``: one instance per container
- ``Lifetime.SCOPED``: one instance per active scope (e.g. per request)

Transient vs singleton
----------------------

.. literalinclude:: ../../examples/ex01_basics/ex02_lifetimes.py
   :language: python

Scoped
------

Scoped lifetimes are covered in :doc:`scopes` because scopes also define *cleanup*.

One important rule of thumb:

- Use **SINGLETON** for pure, long-lived services (configuration, stateless clients).
- Use **SCOPED** for per-request/per-job state (DB sessions, unit-of-work, request context).
- Use **TRANSIENT** for lightweight objects and pure coordinators.

Auto-registration lifetime
--------------------------

Explicit ``register()`` defaults to transient (unless you pass a lifetime).

Auto-registration uses the container's configuration:

.. code-block:: python

   from diwire import Container, Lifetime

   container = Container(autoregister_default_lifetime=Lifetime.TRANSIENT)

