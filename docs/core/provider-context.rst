.. meta::
   :description: provider_context in diwire: ContextVar-backed resolver binding and fallback resolution/injection.

provider_context
=================

Sometimes you can't (or don't want to) pass a :class:`diwire.Container` through every layer of your app. For those
cases, diwire provides :data:`diwire.provider_context`: a shared :class:`diwire.ProviderContext` instance.

What it is (and isn't)
----------------------

- Resolver binding is **task/thread-safe** and uses ``contextvars``.
- ``resolve`` / ``aresolve`` / ``enter_scope`` use the currently bound resolver first, and fall back
  to the latest container configured for this ``ProviderContext``.
- ``inject`` can use one of three resolver sources at call time:
  explicit ``diwire_resolver``, bound resolver from ``provider_context``, or fallback container compile.
- Fallback container policy is **last container wins** per ``ProviderContext`` instance.

Basic usage
-----------

1. Build/configure a container (this automatically registers fallback for ``provider_context`` calls).
2. Use ``@provider_context.inject`` for function wrappers.
3. Optionally bind resolver context explicitly when you need call-local precedence:

   .. code-block:: python

      with container.compile():
          value = provider_context.resolve(MyDependency)

Runnable example: :doc:`/howto/examples/provider-context`.

Testing note
------------

Prefer one of:

- pass ``diwire_resolver=container.compile()`` explicitly in wrappers, or
- create an app-owned ``ProviderContext()`` per test for isolation.
