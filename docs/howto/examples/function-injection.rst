.. meta::
   :description: diwire function injection examples: Injected marker, injected wrapper behavior, and per-call scoped injection.

Function injection
==================

Injected marker (Annotated[T, Injected()])
------------------------------------------

Demonstrates how to mark function parameters for dependency injection using
``Annotated[T, Injected()]``.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass
   from typing import Annotated

   from diwire import Container, Injected


   @dataclass
   class EmailService:
       """Service for sending emails."""

       smtp_host: str = "smtp.example.com"

       def send(self, to: str, subject: str) -> str:
           return f"Email sent to {to}: {subject} (via {self.smtp_host})"


   @dataclass
   class Logger:
       """Simple logger service."""

       def log(self, message: str) -> None:
           print(f"[LOG] {message}")


   def send_welcome_email(
       email_service: Annotated[EmailService, Injected()],
       logger: Annotated[Logger, Injected()],
       user_email: str,
       user_name: str,
   ) -> str:
       """Send a welcome email to a new user.

       Parameters marked with Injected() are injected by the container.
       Regular parameters (user_email, user_name) must be provided by caller.
       """
       logger.log(f"Sending welcome email to {user_name}")
       return email_service.send(user_email, f"Welcome, {user_name}!")


   def main() -> None:
       container = Container()

       # Register services
       container.register(EmailService, instance=EmailService(smtp_host="mail.company.com"))
       container.register(Logger)

       # Resolve the function - returns an InjectedFunction wrapper
       send_email = container.resolve(send_welcome_email)

       print(f"Resolved function type: {type(send_email)}")
       print(f"Function name preserved: {send_email}")
       print()

       # Call the function - only provide non-injected parameters
       result = send_email(user_email="alice@example.com", user_name="Alice")
       print(f"\nResult: {result}")

       # Keyword arguments are recommended for clarity
       result2 = send_email(user_email="bob@example.com", user_name="Bob")
       print(f"Result: {result2}")


   if __name__ == "__main__":
       main()

Injected wrapper behavior
-------------------------

Demonstrates:

- fresh dependency resolution on each call
- signature transformation (injected params removed)
- overriding injected dependencies with explicit kwargs

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass, field
   from typing import Annotated

   from diwire import Container, Injected, Lifetime


   @dataclass
   class Counter:
       """A transient counter that tracks its instance number."""

       _counter: int = field(default=0, init=False, repr=False)
       instance_number: int = field(default=0, init=False)

       def __post_init__(self) -> None:
           Counter._counter += 1
           self.instance_number = Counter._counter


   def process_item(
       counter: Annotated[Counter, Injected()],
       item_id: int,
   ) -> str:
       """Process an item, using a counter service."""
       return f"Processing item {item_id} with counter instance #{counter.instance_number}"


   def main() -> None:
       container = Container()
       container.register(Counter, lifetime=Lifetime.TRANSIENT)

       injected_func = container.resolve(process_item)

       # 1. Fresh resolution on each call
       print("Fresh resolution on each call:")
       for i in range(1, 4):
           result = injected_func(item_id=i)
           print(f"  {result}")

       # 2. Signature transformation
       print(f"\nOriginal signature: {process_item.__code__.co_varnames[:2]}")
       print(f"Injected signature: {injected_func.__signature__}")
       print("  (Note: 'counter' parameter is removed from signature)")

       # 3. Override injected dependency with explicit kwarg
       print("\nOverriding injected dependency:")
       custom_counter = Counter()
       custom_counter.instance_number = 999
       result = injected_func(item_id=100, counter=custom_counter)
       print(f"  {result}")


   if __name__ == "__main__":
       main()

Per-call scope (ScopedInjected)
-------------------------------

Demonstrates how ``resolve(func, scope=...)`` returns a ``ScopedInjected`` that
creates a new scope for each function call. This is useful for request handlers
where each call needs its own scope.

.. code-block:: python
   :class: diwire-example py-run

   import random
   from dataclasses import dataclass
   from enum import Enum
   from typing import Annotated

   from diwire import Container, Injected, Lifetime


   class Scope(str, Enum):
       """Application scope definitions."""

       REQUEST = "request"


   @dataclass
   class RequestSession:
       """Session shared within a single request."""

       session_id: int = 0

       def __post_init__(self) -> None:
           self.session_id = random.randint(1000, 9999)


   @dataclass
   class UserService:
       """Service that uses the request session."""

       session: RequestSession

       def get_user(self, user_id: int) -> str:
           return f"User {user_id} (session: {self.session.session_id})"


   @dataclass
   class AuditService:
       """Service that also uses the request session."""

       session: RequestSession

       def log_access(self, user_id: int) -> str:
           return f"Logged access for user {user_id} (session: {self.session.session_id})"


   def handle_request(
       user_id: int,
       *,
       user_service: Annotated[UserService, Injected()],
       audit_service: Annotated[AuditService, Injected()],
   ) -> dict[str, str]:
       """Handle a request - both services should share the same session."""
       return {
           "user": user_service.get_user(user_id),
           "audit": audit_service.log_access(user_id),
       }


   def main() -> None:
       container = Container()

       # RequestSession is SCOPED - shared within a scope
       container.register(
           RequestSession,
           lifetime=Lifetime.SCOPED,
           scope=Scope.REQUEST,
       )
       container.register(UserService)
       container.register(AuditService)

       # Resolve with scope parameter returns ScopedInjected
       handler = container.resolve(handle_request, scope=Scope.REQUEST)
       print(f"Handler type: {type(handler)}")

       print("\nEach call creates a new scope:")
       for i in range(1, 4):
           result = handler(user_id=i)
           print(f"\n  Request {i}:")
           print(f"    {result['user']}")
           print(f"    {result['audit']}")
           # Note: session IDs match within each request but differ across requests


   if __name__ == "__main__":
       main()

Read more
---------

- :doc:`../../core/function-injection`
- :doc:`../../core/scopes`
