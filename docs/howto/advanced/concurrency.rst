.. meta::
   :description: Concurrency and diwire: resolving from multiple threads/tasks, request scopes, and container_context behavior with contextvars and threadpools.

Concurrency
===========

General guidance
----------------

- Treat the container as **immutable after startup**: register everything up front, then resolve concurrently.
- Avoid mutating registrations while other threads/tasks are resolving.

Threads and free-threaded Python
--------------------------------

diwire uses internal locking to make singleton/scoped-singleton resolution safe under concurrent access (including
free-threaded Python builds).

Async tasks
-----------

In async code, prefer:

- async factories + :meth:`diwire.Container.aresolve`
- ``async with container.enter_scope(...):`` for scoped async cleanup

container_context and threadpools
---------------------------------

Web frameworks sometimes run sync handlers in a threadpool. diwire's :data:`diwire.container_context` uses
``contextvars`` and also includes a thread-local fallback for cases where the execution context is not copied.

