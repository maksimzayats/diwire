.. meta::
   :description: How to override diwire registrations in tests: register fakes, use instances, and prefer a fresh container per test.

Overrides
=========

The simplest (and most reliable) testing strategy is:

- create a fresh :class:`diwire.Container` per test
- register test doubles (fakes/mocks) up front
- resolve your entrypoint (service/handler) from that container

Override by registering again
-----------------------------

Registrations are replaceable. In general, override **before** the first resolve:

.. code-block:: python

   from typing import Protocol

   from diwire import Container, Lifetime

   container = Container(autoregister_concrete_types=False)

   class EmailClient(Protocol):
       def send(self, to: str, subject: str) -> None: ...


   class RealEmailClient:
       def send(self, to: str, subject: str) -> None:
           ...


   class FakeEmailClient:
       def send(self, to: str, subject: str) -> None:
           ...


   container.add_concrete(RealEmailClient, provides=EmailClient,
       lifetime=Lifetime.SCOPED,
   )
   # In tests: override BEFORE resolving anything that depends on it.
   container.add_concrete(FakeEmailClient, provides=EmailClient,
       lifetime=Lifetime.SCOPED,
   )

Override using an instance (force a singleton)
----------------------------------------------

Registering an instance is a great way to override something even if it was resolved earlier:

.. code-block:: python

   fake = FakeEmailClient()
   container.add_instance(fake, provides=EmailClient)

Because the container uses the instance directly, subsequent resolves return exactly that object.
