.. meta::
   :description: Compilation in diwire: compile() precomputes providers to remove reflection/dict lookups on hot paths, and auto-compiles on first resolve by default.

Compilation
===========

diwire can precompute the dependency graph into specialized provider objects to reduce overhead on hot paths.

The two knobs are:

- :meth:`diwire.Container.compile` - compile explicitly after registration
- ``Container(auto_compile=...)`` - auto-compile on first resolve (default: enabled)

When to use it
--------------

Compilation is most useful when:

- you resolve the same graph many times (web requests, worker jobs)
- you care about micro-latency and throughput

Basic usage
-----------

.. code-block:: python

   from dataclasses import dataclass

   from diwire import Container, Lifetime


   @dataclass
   class ServiceA:
       ...


   @dataclass
   class ServiceB:
       a: ServiceA


   container = Container(auto_compile=False)
   container.register(ServiceA, lifetime=Lifetime.SINGLETON)
   container.register(ServiceB, lifetime=Lifetime.TRANSIENT)

   container.compile()
   b = container.resolve(ServiceB)

Runnable example
----------------

See the runnable script in :doc:`/howto/examples/basics` (Compilation section).

Notes and limitations
---------------------

- Not every registration can be compiled (for example: async factories, open generic registrations, and some function
  factories). diwire will still resolve them correctly; they just won't use the fastest compiled path.
- Auto-compilation happens when resolving outside of an active scope. Scoped graphs are compiled separately when
  possible.
