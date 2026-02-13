.. meta::
   :description: resolver_context in diwire: ContextVar-backed resolver binding and fallback resolution/injection.

resolver_context
=================

Sometimes you can't (or don't want to) pass a :class:`diwire.Container` through every layer of your app. For those
cases, diwire provides :data:`diwire.resolver_context`: a shared :class:`diwire.ResolverContext` instance.

What it is (and isn't)
----------------------

- Resolver binding is **task/thread-safe** and uses ``contextvars``.
- ``resolve`` / ``aresolve`` / ``enter_scope`` use the currently bound resolver first, and fall back
  to the latest container configured for this ``ResolverContext``.
- ``inject`` can use one of three resolver sources at call time:
  explicit ``diwire_resolver``, bound resolver from ``resolver_context``, or fallback container compile
  when the fallback container is configured with ``use_resolver_context=True``.
- Fallback container policy is **last container wins** per ``ResolverContext`` instance.

Basic usage
-----------

1. Build/configure a container (this automatically registers fallback for ``resolver_context`` calls).
2. Use ``@resolver_context.inject`` for function wrappers.
3. Optionally bind resolver context explicitly when you need call-local precedence:

   .. code-block:: python

      from diwire import Container, resolver_context


      class MyDependency:
          ...


      container = Container()
      container.add(MyDependency)

      with container.compile():
          value = resolver_context.resolve(MyDependency)

      assert isinstance(value, MyDependency)

Runnable example: :doc:`/howto/examples/resolver-context`.

Testing note
------------

Prefer one of:

- pass ``diwire_resolver=container.compile()`` explicitly in wrappers, or
- create an app-owned ``ResolverContext()`` per test for isolation.
