.. meta::
   :description: Concurrency and diwire: resolving from multiple threads/tasks, request scopes, LockMode behavior, and resolver_context considerations.

Concurrency
===========

General guidance
----------------

- Treat the container as **immutable after startup**: register everything up front, then resolve concurrently.
- Avoid mutating registrations while other threads/tasks are resolving.
- Configure lock behavior explicitly with :class:`diwire.LockMode`.

LockMode
--------

``Container(lock_mode=...)`` sets the default for non-instance providers.

- ``"auto"``: infer by graph. If async specs exist, behaves like ``ASYNC``; otherwise like ``THREAD``.
- ``LockMode.THREAD``: lock only sync cached paths.
- ``LockMode.ASYNC``: lock only async-required cached paths.
- ``LockMode.NONE``: disable locks on cached paths.

.. note::

   In mixed graphs (both sync and async specs), ``lock_mode="auto"`` promotes to
   ``LockMode.ASYNC`` for auto-mode registrations. That means sync cached paths using
   ``"auto"`` do not get thread locks. This is expected and is usually fine for asyncio
   apps that resolve on a single event-loop thread per worker.

   If you resolve sync cached providers from multiple threads, set ``LockMode.THREAD``
   at the container or registration level.

Registration-level overrides are available for ``add``, ``add_factory``,
``add_generator``, and ``add_context_manager``:

.. code-block:: python

   from diwire import Container, LockMode


   class Service:
       ...


   class Cache:
       ...


   class Client:
       ...


   def build_service() -> Service:
       return Service()


   def build_cache() -> Cache:
       return Cache()


   def build_client() -> Client:
       return Client()

   container = Container(lock_mode="auto")
   container.add_factory(build_service, provides=Service)  # inherits AUTO via "from_container"
   container.add_factory(build_cache, provides=Cache, lock_mode=LockMode.THREAD)
   container.add_factory(build_client, provides=Client, lock_mode=LockMode.NONE)

Use ``lock_mode="from_container"`` to explicitly inherit the container default.
``add_instance`` has no lock override and always uses ``LockMode.NONE``.

Threads and free-threaded Python
--------------------------------

diwire can use thread locks to make root-scoped and scoped sync cached resolution safe under concurrent access
(including free-threaded Python builds), depending on effective ``LockMode``.

Async tasks
-----------

In async code, prefer:

- async factories + :meth:`diwire.Container.aresolve`
- ``async with container.enter_scope(...):`` for scoped async cleanup

resolver_context and threadpools
---------------------------------

Web frameworks sometimes run sync handlers in a threadpool. :data:`diwire.resolver_context` is process-global for
that instance, so it is visible from worker threads without any special context propagation.

Because the binding is global, avoid rebinding :data:`diwire.resolver_context` in parallel test runs. For isolation,
prefer passing a :class:`diwire.Container` / resolver explicitly or using an app-owned :class:`diwire.ResolverContext`
instance.
