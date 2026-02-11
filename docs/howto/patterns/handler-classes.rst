.. meta::
   :description: Injecting into handler/controller classes with diwire: use container_context.inject() on instance methods while keeping framework-friendly signatures.

Handler classes (methods)
=========================

For controller/handler classes, you often want DI on instance methods (not just free functions).

Use :meth:`diwire.ContainerContext.inject` (via :data:`diwire.container_context`) on methods to create injected callables
that still behave like methods.

Example (runnable)
------------------

See :doc:`../examples/container-context`.
