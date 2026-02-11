.. meta::
   :description: Programming to interfaces with diwire: bind Protocols/ABCs to concrete implementations and swap them in tests/environments.

Interfaces (Protocol/ABC)
=========================

If your code depends on abstractions (Protocols/ABCs), you must tell diwire what concrete class to build.

Use ``add_concrete(..., provides=...)``:

.. code-block:: python

   from typing import Protocol

   from diwire import Container, Lifetime


   class Clock(Protocol):
       def now(self) -> str: ...


   class SystemClock:
       def now(self) -> str:
           return "now"


   container = Container(autoregister_concrete_types=False)
   container.add_concrete(SystemClock, provides=Clock,
       lifetime=Lifetime.SCOPED,
   )

Example (runnable)
------------------

See :doc:`../examples/registration-methods`.
