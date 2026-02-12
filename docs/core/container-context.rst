.. meta::
   :description: container_context in diwire: process-global ContainerContext binding and deferred registration replay.

container_context
=================

Sometimes you can't (or don't want to) pass a :class:`diwire.Container` through every layer of your app. For those
cases, diwire provides :data:`diwire.container_context`: a shared :class:`diwire.ContainerContext` instance.

What it is (and isn't)
----------------------

- ``container_context`` stores **one shared active container** per ``ContainerContext`` instance.
- The binding is **process-global** for that instance (it is not task-local and not thread-local).
- It supports **deferred replay**: registration calls made before a container is bound are recorded and replayed when
  you later call ``set_current(container)``.

Basic usage
-----------

1. Build/configure your container.
2. Bind it once: ``container_context.set_current(container)``.
3. Use ``container_context.add_*`` / ``container_context.inject`` / ``container_context.resolve`` without passing
   the container around.

Runnable example: :doc:`/howto/examples/container-context`.

Testing note
------------

Because the binding is process-global, tests should either:

- bind once at session startup, or
- create an app-owned ``ContainerContext()`` instance for isolation.
