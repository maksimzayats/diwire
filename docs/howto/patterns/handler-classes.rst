.. meta::
   :description: Injecting into handler/controller classes with diwire: use provider_context.inject() on instance methods while keeping framework-friendly signatures.

Handler classes (methods)
=========================

For controller/handler classes, you often want DI on instance methods (not just free functions).

Use :meth:`diwire.ProviderContext.inject` (via :data:`diwire.provider_context`) on methods to create injected callables
that still behave like methods.

Example (runnable)
------------------

See :doc:`../examples/provider-context`.
