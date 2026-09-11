.. meta::
   :description: Use diwire with Celery tasks via resolver_context injection and request-scoped cleanup per task execution.
   :keywords: celery dependency injection, python dependency injection celery, task scope dependency injection

Celery
======

diwire supports Celery tasks without a dedicated framework adapter.
Use :meth:`diwire.ResolverContext.inject` on task callables and annotate injected
parameters with ``Injected[T]``.

Minimal setup
-------------

.. code-block:: python

   from celery import Celery

   from diwire import Container, Injected, Scope, resolver_context

   app = Celery("demo", broker="memory://", backend="cache+memory://")
   app.conf.update(task_always_eager=True, task_store_eager_result=True)

   container = Container()


   class Service:
       def run(self, value: int) -> int:
           return value + 1


   container.add(Service, provides=Service)


   @app.task(name="demo.add-one")
   @resolver_context.inject(scope=Scope.REQUEST)
   def add_one(value: int, service: Injected[Service]) -> int:
       return service.run(value)


   assert add_one.delay(3).get(timeout=5.0) == 4

Decorator order matters: keep ``@resolver_context.inject(...)`` below ``@app.task`` so Celery
registers the injected wrapper signature.

Task scope and cleanup
----------------------

``scope=Scope.REQUEST`` works well as a per-task scope. Each task execution gets an isolated scoped
resolver, and scoped cleanup runs when task execution finishes.

That means request-scoped providers, context managers, and generator providers behave predictably
for background jobs the same way they do in web request handlers.

Bound tasks
-----------

Bound tasks keep the ``self``/task instance argument normally; inject only the parameters marked as
``Injected[...]``.

.. code-block:: python

   from celery import Celery, Task

   from diwire import Container, Injected, Scope, resolver_context

   app = Celery("demo", broker="memory://", backend="cache+memory://")
   app.conf.update(task_always_eager=True, task_store_eager_result=True)
   container = Container()


   class Service:
       def run(self, value: int) -> int:
           return value + 1


   container.add(Service, provides=Service)


   @app.task(bind=True, name="demo.bound")
   @resolver_context.inject(scope=Scope.REQUEST)
   def bound(task: Task, value: int, service: Injected[Service]) -> str:
       return f"{task.name}:{service.run(value)}"


   assert bound.delay(9).get(timeout=5.0) == "demo.bound:10"

Testing
-------

- In-process integration tests: configure Celery with eager mode
  (``task_always_eager=True``) and call ``delay(...).get(...)``.
- End-to-end tests with a real worker + broker are available in this repository:
  run ``just test-e2e-celery``.
