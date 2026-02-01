.. meta::
   :description: diwire patterns examples: per-request scoped handlers, unit-of-work with scoped sessions, container_context for instance methods, and interface binding via concrete_class.

Patterns
========

HTTP request handler pattern (per-request scope)
------------------------------------------------

Demonstrates a common web pattern:

- each request gets its own scope
- multiple services share a request-scoped context
- the handler is resolved via ``container.resolve(..., scope="request")``

.. code-block:: python
   :class: diwire-example py-run

   from enum import Enum
   from typing import Annotated

   from diwire import Container, Injected, Lifetime


   class Scope(str, Enum):
       REQUEST = "request"


   class RequestContext:
       _counter = 0

       def __init__(self) -> None:
           type(self)._counter += 1
           self.request_id = f"req-{type(self)._counter}"
           self.user_id: int | None = None


   class AuthService:
       def __init__(self, ctx: RequestContext) -> None:
           self.ctx = ctx

       def authenticate(self, token: str) -> None:
           if token.startswith("valid-"):
               self.ctx.user_id = int(token.removeprefix("valid-"))


   class AuditLogger:
       def __init__(self, ctx: RequestContext) -> None:
           self.ctx = ctx

       def log(self, action: str) -> None:
           print(f"[{self.ctx.request_id}] user={self.ctx.user_id}: {action}")


   def handle_request(
       token: str,
       auth: Annotated[AuthService, Injected()],
       audit: Annotated[AuditLogger, Injected()],
       ctx: Annotated[RequestContext, Injected()],
   ) -> dict[str, str | int | None]:
       auth.authenticate(token)
       audit.log("handle_request")
       return {"request_id": ctx.request_id, "user_id": ctx.user_id}


   def main() -> None:
       container = Container()
       container.register(RequestContext, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
       container.register(AuthService)
       container.register(AuditLogger)

       handler = container.resolve(handle_request, scope=Scope.REQUEST)

       print(handler(token="valid-42"))
       print(handler(token="invalid"))


   if __name__ == "__main__":
       main()

Repository / unit-of-work pattern
---------------------------------

Demonstrates a unit-of-work pattern where the database session is shared within a scope.

Per-call unit of work (ScopedInjected)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass
   from enum import Enum
   from typing import Annotated

   from diwire import Container, Injected, Lifetime


   class Scope(str, Enum):
       UNIT_OF_WORK = "unit_of_work"


   class Session:
       _counter = 0

       def __init__(self) -> None:
           type(self)._counter += 1
           self.session_id = type(self)._counter

       def commit(self) -> None:
           print(f"[Session {self.session_id}] COMMIT")


   @dataclass
   class UserRepository:
       session: Session

       def create(self, username: str) -> str:
           print(f"[Session {self.session.session_id}] INSERT user {username!r}")
           return username


   def create_user(
       username: str,
       session: Annotated[Session, Injected()],
       user_repo: Annotated[UserRepository, Injected()],
   ) -> dict[str, str | int]:
       user = user_repo.create(username)
       session.commit()
       return {"user": user, "session_id": session.session_id}


   def main() -> None:
       container = Container()
       container.register(Session, lifetime=Lifetime.SCOPED, scope=Scope.UNIT_OF_WORK)
       container.register(UserRepository)

       handler = container.resolve(create_user, scope=Scope.UNIT_OF_WORK)
       print(handler(username="alice"))
       print(handler(username="bob"))


   if __name__ == "__main__":
       main()

Manual unit of work scope (enter_scope)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``enter_scope()`` when you want to manage the scope explicitly.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass
   from enum import Enum

   from diwire import Container, Lifetime


   class Scope(str, Enum):
       UNIT_OF_WORK = "unit_of_work"


   class Session:
       _counter = 0

       def __init__(self) -> None:
           type(self)._counter += 1
           self.session_id = type(self)._counter


   @dataclass
   class UserRepository:
       session: Session


   def main() -> None:
       container = Container()
       container.register(Session, lifetime=Lifetime.SCOPED, scope=Scope.UNIT_OF_WORK)
       container.register(UserRepository)

       with container.enter_scope(Scope.UNIT_OF_WORK) as scope:
           repo1 = scope.resolve(UserRepository)
           repo2 = scope.resolve(UserRepository)
           session = scope.resolve(Session)

           print(f"Same session: {repo1.session is repo2.session is session}")
           print(f"session_id={session.session_id}")


   if __name__ == "__main__":
       main()

Class methods with container_context
------------------------------------

``container_context.resolve()`` works on instance methods. This is useful for controller/handler classes
where you want dependency injection without passing the container around.

Instance method injection
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python
   :class: diwire-example py-run

   from typing import Annotated

   from diwire import Container, Injected, Lifetime, container_context


   class Logger:
       def info(self, message: str) -> None:
           print(f"[INFO] {message}")


   class Controller:
       def __init__(self, prefix: str) -> None:
           self.prefix = prefix

       @container_context.resolve()
       def ping(self, logger: Annotated[Logger, Injected()]) -> str:
           logger.info(f"{self.prefix}/ping")  # noqa: G004
           return "pong"


   def main() -> None:
       container = Container()
       container.register(Logger, lifetime=Lifetime.SINGLETON)

       token = container_context.set_current(container)
       try:
           controller = Controller(prefix="/v1")
           print(controller.ping())
       finally:
           container_context.reset(token)


   if __name__ == "__main__":
       main()

Instance method with caller args
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Injected params and caller-provided params can be mixed.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass
   from typing import Annotated

   from diwire import Container, Injected, container_context


   @dataclass
   class UserRepository:
       def get_username(self, user_id: int) -> str:
           return f"user-{user_id}"


   class Controller:
       @container_context.resolve()
       def get_user(
           self,
           user_id: int,
           repo: Annotated[UserRepository, Injected()],
       ) -> str:
           return repo.get_username(user_id)


   def main() -> None:
       container = Container()
       container.register(UserRepository)

       token = container_context.set_current(container)
       try:
           controller = Controller()
           print(controller.get_user(123))
       finally:
           container_context.reset(token)


   if __name__ == "__main__":
       main()

Interface registration (Protocol/ABC -> concrete_class)
-------------------------------------------------------

Use ``concrete_class=...`` to bind a Protocol/ABC to an implementation.

.. code-block:: python
   :class: diwire-example py-run

   from typing import Protocol

   from diwire import Container, Lifetime


   class Clock(Protocol):
       def now(self) -> str: ...


   class SystemClock:
       def now(self) -> str:
           return "2026-02-01T00:00:00Z"


   class Greeter:
       def __init__(self, clock: Clock) -> None:
           self.clock = clock

       def greet(self) -> str:
           return f"Hello at {self.clock.now()}"


   def main() -> None:
       container = Container()
       container.register(Clock, concrete_class=SystemClock, lifetime=Lifetime.SINGLETON)

       greeter = container.resolve(Greeter)
       print(greeter.greet())


   if __name__ == "__main__":
       main()

Read more
---------

- :doc:`../../core/registration`
- :doc:`../patterns/index`
