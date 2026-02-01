.. meta::
   :description: Injecting into handler/controller classes with diwire: use container_context.resolve() on instance methods while keeping framework-friendly signatures.

Handler classes (methods)
=========================

For controller/handler classes, you often want DI on instance methods (not just free functions).

Use :func:`diwire.container_context.resolve` on methods to create injected callables that still behave like methods.

Example (runnable)
------------------

.. literalinclude:: ../../../examples/ex05_patterns/ex03_class_methods.py
   :language: python

