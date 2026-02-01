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

See the runnable script in :doc:`/howto/examples/basics` (Lifetimes section).

.. code-block:: python

   from diwire import Container, Lifetime


   class TransientService:
       pass


   class SingletonService:
       pass


   container = Container(autoregister=False)
   container.register(TransientService, lifetime=Lifetime.TRANSIENT)
   container.register(SingletonService, lifetime=Lifetime.SINGLETON)

   assert container.resolve(TransientService) is not container.resolve(TransientService)
   assert container.resolve(SingletonService) is container.resolve(SingletonService)

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
