.. meta::
   :description: Concurrency and diwire: resolving from multiple threads/tasks, request scopes, and container_context behavior with contextvars and threadpools.

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

Registration-level overrides are available for ``register_concrete``, ``register_factory``,
``register_generator``, and ``register_context_manager``:

.. code-block:: python

   from diwire import Container, LockMode

   container = Container(lock_mode="auto")
   container.register_factory(Service, factory=build_service)  # inherits AUTO via "from_container"
   container.register_factory(Cache, factory=build_cache, lock_mode=LockMode.THREAD)
   container.register_factory(Client, factory=build_client, lock_mode=LockMode.NONE)

Use ``lock_mode="from_container"`` to explicitly inherit the container default.
``register_instance`` has no lock override and always uses ``LockMode.NONE``.

Threads and free-threaded Python
--------------------------------

diwire can use thread locks to make singleton/scoped-singleton sync resolution safe under concurrent access
(including free-threaded Python builds), depending on effective ``LockMode``.

Async tasks
-----------

In async code, prefer:

- async factories + :meth:`diwire.Container.aresolve`
- ``async with container.enter_scope(...):`` for scoped async cleanup

container_context and threadpools
---------------------------------

Web frameworks sometimes run sync handlers in a threadpool. diwire's :data:`diwire.container_context` uses
``contextvars`` and also includes a thread-local fallback for cases where the execution context is not copied.
