.. meta::
   :description: diwire scopes examples: enter_scope(), SCOPED lifetime, nested scopes, and generator factories with cleanup.

Scopes
======

Scope basics
------------

Demonstrates how to use scopes with ``enter_scope()``.
Scopes allow grouping related service resolutions together.

.. code-block:: python
   :class: diwire-example py-run

   from enum import Enum

   from diwire import Container


   class Scope(str, Enum):
       """Application scope definitions."""

       REQUEST = "request"


   class RequestContext:
       """Holds request-specific data."""

       def __init__(self) -> None:
           self.request_id = id(self)

       def __repr__(self) -> str:
           return f"RequestContext(request_id={self.request_id})"


   def main() -> None:
       container = Container()
       container.register(RequestContext)

       # Using enter_scope() with an Enum value
       print("Scope usage with context manager:\n")

       with container.enter_scope(Scope.REQUEST) as scope:
           # Resolve services within the scope
           ctx1 = scope.resolve(RequestContext)
           ctx2 = scope.resolve(RequestContext)

           print(f"Inside scope '{Scope.REQUEST.value}':")
           print(f"  ctx1: {ctx1}")
           print(f"  ctx2: {ctx2}")
           print(f"  Same instance (transient): {ctx1 is ctx2}")

       # Each scope is independent
       print("\nMultiple independent scopes:")

       with container.enter_scope(Scope.REQUEST) as scope1:
           ctx_a = scope1.resolve(RequestContext)
           print(f"  Scope 1 context: {ctx_a}")

       with container.enter_scope(Scope.REQUEST) as scope2:
           ctx_b = scope2.resolve(RequestContext)
           print(f"  Scope 2 context: {ctx_b}")

       print(f"  Different instances: {ctx_a is not ctx_b}")


   if __name__ == "__main__":
       main()

SCOPED lifetime (shared per scope)
----------------------------------

Demonstrates ``SCOPED``:

- same instance within a scope
- different instance across scopes

.. code-block:: python
   :class: diwire-example py-run

   from enum import Enum

   from diwire import Container, Lifetime


   class Scope(str, Enum):
       """Application scope definitions."""

       REQUEST = "request"


   class Session:
       """A session that should be shared within a request scope."""

       def __init__(self) -> None:
           self.session_id = id(self)

       def __repr__(self) -> str:
           return f"Session(id={self.session_id})"


   class Repository:
       """Repository that uses the current session."""

       def __init__(self, session: Session) -> None:
           self.session = session


   def main() -> None:
       container = Container()

       # Register Session as SCOPED for REQUEST scope
       container.register(
           Session,
           lifetime=Lifetime.SCOPED,
           scope=Scope.REQUEST,
       )
       container.register(Repository)

       print("SCOPED behavior:\n")

       # Within the same scope, Session is shared
       with container.enter_scope(Scope.REQUEST) as scope:
           session1 = scope.resolve(Session)
           session2 = scope.resolve(Session)
           repo = scope.resolve(Repository)

           print("Request Scope 1:")
           print(f"  session1: {session1}")
           print(f"  session2: {session2}")
           print(f"  repo.session: {repo.session}")
           print(f"  All same instance: {session1 is session2 is repo.session}")

       # Different scope = different Session instance
       with container.enter_scope(Scope.REQUEST) as scope:
           session3 = scope.resolve(Session)
           repo2 = scope.resolve(Repository)

           print("\nRequest Scope 2:")
           print(f"  session3: {session3}")
           print(f"  repo2.session: {repo2.session}")
           print(f"  Same within scope: {session3 is repo2.session}")
           print(f"  Different from scope 1: {session3 is not session1}")


   if __name__ == "__main__":
       main()

Nested scopes
-------------

Demonstrates hierarchical scope nesting where child scopes can access services
from parent scopes.

.. code-block:: python
   :class: diwire-example py-run

   from enum import Enum

   from diwire import Container, Lifetime


   class Scope(str, Enum):
       """Application scope definitions."""

       REQUEST = "request"
       HANDLER = "handler"


   class RequestContext:
       """Request-level context, shared within a request."""

       def __init__(self) -> None:
           self.request_id = id(self)


   class HandlerContext:
       """Handler-level context, specific to each handler invocation."""

       def __init__(self) -> None:
           self.handler_id = id(self)


   def main() -> None:
       container = Container()

       container.register(
           RequestContext,
           lifetime=Lifetime.SCOPED,
           scope=Scope.REQUEST,
       )
       container.register(
           HandlerContext,
           lifetime=Lifetime.SCOPED,
           scope=Scope.HANDLER,
       )

       print("Nested scopes demonstration:\n")

       with container.enter_scope(Scope.REQUEST) as request_scope:
           request_ctx = request_scope.resolve(RequestContext)
           print(f"Request scope - RequestContext id: {request_ctx.request_id}")

           # Create nested handler scopes
           with request_scope.enter_scope(Scope.HANDLER) as handler_scope1:
               handler_ctx1 = handler_scope1.resolve(HandlerContext)
               # Parent's RequestContext is accessible from child
               inherited_request_ctx = handler_scope1.resolve(RequestContext)

               print("\n  Handler scope 1:")
               print(f"    HandlerContext id: {handler_ctx1.handler_id}")
               print(f"    RequestContext id: {inherited_request_ctx.request_id}")
               print(f"    Same request context: {inherited_request_ctx is request_ctx}")

           with request_scope.enter_scope(Scope.HANDLER) as handler_scope2:
               handler_ctx2 = handler_scope2.resolve(HandlerContext)
               inherited_request_ctx2 = handler_scope2.resolve(RequestContext)

               print("\n  Handler scope 2:")
               print(f"    HandlerContext id: {handler_ctx2.handler_id}")
               print(f"    RequestContext id: {inherited_request_ctx2.request_id}")
               print(f"    Same request context: {inherited_request_ctx2 is request_ctx}")
               print(f"    Different handler context: {handler_ctx2 is not handler_ctx1}")


   if __name__ == "__main__":
       main()

Generator factories (cleanup on scope exit)
-------------------------------------------

Demonstrates generator factory support:

- the yielded instance is used by the container
- the generator is closed on scope exit

.. code-block:: python
   :class: diwire-example py-run

   from __future__ import annotations

   from collections.abc import Generator
   from enum import Enum

   from diwire import Container, Lifetime


   class Scope(str, Enum):
       """Application scope definitions."""

       REQUEST = "request"


   class Session:
       """A session that needs cleanup when the scope ends."""

       def __init__(self) -> None:
           self.session_id = id(self)
           self.closed = False

       def close(self) -> None:
           self.closed = True
           print(f"Session {self.session_id} closed")

       def __repr__(self) -> str:
           return f"Session(id={self.session_id}, closed={self.closed})"


   def session_factory() -> Generator[Session, None, None]:
       session = Session()
       print(f"Session {session.session_id} opened")
       try:
           yield session
       finally:
           session.close()


   def main() -> None:
       container = Container()
       container.register(
           Session,
           factory=session_factory,
           lifetime=Lifetime.SCOPED,
           scope=Scope.REQUEST,
       )

       print("Generator factory scope behavior:\n")
       with container.enter_scope(Scope.REQUEST):
           session1 = container.resolve(Session)
           session2 = container.resolve(Session)
           print(f"session1: {session1}")
           print(f"session2: {session2}")
           print(f"Same instance: {session1 is session2}")

       print("\nScope exited; generator cleanup should have run.")


   if __name__ == "__main__":
       main()

Read more
---------

- :doc:`../../core/scopes`
- :doc:`../../core/lifetimes`
- :doc:`../../core/errors`
