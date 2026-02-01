.. meta::
   :description: diwire error examples: circular dependency detection, missing dependency errors, and scope mismatch errors.

Errors
======

Circular dependencies
---------------------

Demonstrates how diwire detects and reports circular dependencies.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass

   from diwire import Container
   from diwire.exceptions import DIWireCircularDependencyError


   # Circular dependency: ServiceA -> ServiceB -> ServiceA
   @dataclass
   class ServiceA:
       """Service that depends on ServiceB."""

       b: "ServiceB"


   @dataclass
   class ServiceB:
       """Service that depends on ServiceA (creating a cycle)."""

       a: ServiceA


   def main() -> None:
       # Disable compilation to ensure we hit the runtime resolution path that reports
       # DIWireCircularDependencyError (instead of recursing during compilation).
       container = Container(auto_compile=False)
       container.register(ServiceA)
       container.register(ServiceB)

       print("Attempting to resolve circular dependency chain:")
       print("  ServiceA -> ServiceB -> ServiceA")
       print()

       try:
           container.resolve(ServiceA)
       except DIWireCircularDependencyError as e:
           print("DIWireCircularDependencyError caught!")
           print(f"  Service key: {e.service_key}")
           print(f"  Resolution chain: {' -> '.join(str(k) for k in e.resolution_chain)}")

       # How to avoid: use factories, lazy loading, or restructure dependencies
       print("\nSolutions to avoid circular dependencies:")
       print("  1. Restructure code to break the cycle")
       print("  2. Use a factory to lazily create one of the services")
       print("  3. Introduce an interface/protocol to invert the dependency")


   if __name__ == "__main__":
       main()

Missing dependencies
--------------------

Demonstrates ``DIWireMissingDependenciesError`` when a required dependency cannot be resolved.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass

   from diwire import Container
   from diwire.exceptions import DIWireMissingDependenciesError


   class ExternalAPI:
       """An external API client that requires configuration."""

       def __init__(self, api_key: str) -> None:
           self.api_key = api_key


   @dataclass
   class UserService:
       """Service that depends on ExternalAPI."""

       api: ExternalAPI


   def main() -> None:
       # Disable auto-registration to see DIWireMissingDependenciesError
       container = Container(autoregister=False)

       # Only register UserService, not ExternalAPI
       container.register(UserService)

       print("Attempting to resolve service with missing dependency:")
       print("  UserService requires ExternalAPI, but ExternalAPI is not registered")
       print()

       try:
           container.resolve(UserService)
       except DIWireMissingDependenciesError as e:
           print("DIWireMissingDependenciesError caught!")
           print(f"  Service key: {e.service_key}")
           print(f"  Missing dependencies: {e.missing}")

       # With autoregister=True (default), simple classes would be auto-registered
       print("\nWith autoregister=True (default):")
       container_auto = Container(autoregister=True)
       container_auto.register(UserService)

       # Note: ExternalAPI still fails because it has a non-injectable 'api_key' param
       try:
           container_auto.resolve(UserService)
       except DIWireMissingDependenciesError as e:
           print(f"  Still fails: {e.missing}")
           print("  (ExternalAPI has 'api_key: str' which cannot be auto-resolved)")


   if __name__ == "__main__":
       main()

Scope mismatch
--------------

Demonstrates ``DIWireScopeMismatchError`` when trying to resolve from an exited scope.

.. code-block:: python
   :class: diwire-example py-run

   from enum import Enum

   from diwire import Container, Lifetime
   from diwire.exceptions import DIWireScopeMismatchError


   class Scope(str, Enum):
       """Application scope definitions."""

       REQUEST = "request"


   class RequestSession:
       """Session that must be resolved within a REQUEST scope."""


   def main() -> None:
       container = Container()

       # Register session as SCOPED for REQUEST scope
       container.register(
           RequestSession,
           lifetime=Lifetime.SCOPED,
           scope=Scope.REQUEST,
       )

       # Trying to use a scope after it has exited
       print("Scenario: Using a scope reference after it has exited\n")

       scope_ref = None
       with container.enter_scope(Scope.REQUEST) as scope:
           # Save reference to scope
           scope_ref = scope
           session = scope.resolve(RequestSession)
           print(f"Inside scope: resolved {session}")

       # Now scope has exited but we try to use the saved reference
       print("\nAttempting to resolve from exited scope:")
       try:
           scope_ref.resolve(RequestSession)
       except DIWireScopeMismatchError as e:
           print("  DIWireScopeMismatchError caught!")
           print(f"    Service: {e.service_key}")
           print(f"    Registered scope: {e.registered_scope}")
           print(f"    Current scope: {e.current_scope}")

       # Correct usage - always use scopes within their context manager
       print("\nCorrect usage - resolve within active scope context:")
       with container.enter_scope(Scope.REQUEST) as scope:
           session = scope.resolve(RequestSession)
           print(f"  Successfully resolved: {session}")


   if __name__ == "__main__":
       main()

Scoped resolved outside scope (auto-register safety)
----------------------------------------------------

Demonstrates ``DIWireScopeMismatchError`` when:

- a service is registered only as ``SCOPED``
- you try to resolve it outside the required scope

This prevents the container from silently auto-registering a second, unscoped instance.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass

   from diwire import Container, Lifetime
   from diwire.exceptions import DIWireScopeMismatchError


   @dataclass
   class Session:
       active: bool = True


   def main() -> None:
       container = Container(autoregister=True)
       container.register(Session, lifetime=Lifetime.SCOPED, scope="request")

       print("Resolving a SCOPED service outside its scope:\n")
       try:
           container.resolve(Session)
       except DIWireScopeMismatchError as e:
           print("DIWireScopeMismatchError caught!")
           print(f"  service: {e.service_key}")
           print(f"  registered_scope: {e.registered_scope}")
           print(f"  current_scope: {e.current_scope}")

       print("\nResolving inside the correct scope:")
       with container.enter_scope("request") as scope:
           session = scope.resolve(Session)
           print(f"  session.active={session.active}")


   if __name__ == "__main__":
       main()

Read more
---------

- :doc:`../../core/errors`
- :doc:`../../core/scopes`
- :doc:`../../reference/exceptions`
