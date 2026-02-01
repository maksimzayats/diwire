.. meta::
   :description: diwire real-world patterns examples: request handler scope, repository/unit-of-work, class methods with container_context, and interface registrations.

Patterns
========

HTTP request handler pattern (per-request scope)
------------------------------------------------

Demonstrates a real-world pattern for handling HTTP requests where each request
gets its own scope with shared services.

.. code-block:: python
   :class: diwire-example py-run

   import random
   from dataclasses import dataclass, field
   from enum import Enum
   from typing import Annotated

   from diwire import Container, Injected, Lifetime


   class Scope(str, Enum):
       """Application scope definitions."""

       REQUEST = "request"


   @dataclass
   class RequestContext:
       """Context shared across all services within a single request."""

       request_id: str = field(default_factory=lambda: f"req-{random.randint(1000, 9999)}")
       user_id: int | None = None
       authenticated: bool = False


   @dataclass
   class AuthService:
       """Handles authentication within the request context."""

       ctx: RequestContext

       def authenticate(self, token: str) -> bool:
           # Simulate authentication
           if token.startswith("valid-"):
               self.ctx.authenticated = True
               self.ctx.user_id = int(token.split("-")[1])
               return True
           return False


   @dataclass
   class UserService:
       """User operations using request context."""

       ctx: RequestContext

       def get_current_user(self) -> dict[str, str | int | None]:
           if not self.ctx.authenticated:
               return {"error": "Not authenticated"}
           return {
               "user_id": self.ctx.user_id,
               "request_id": self.ctx.request_id,
           }


   @dataclass
   class AuditLogger:
       """Logs actions with request context."""

       ctx: RequestContext

       def log(self, action: str) -> str:
           return f"[{self.ctx.request_id}] user={self.ctx.user_id}: {action}"


   def handle_get_user(
       auth: Annotated[AuthService, Injected()],
       user_service: Annotated[UserService, Injected()],
       audit: Annotated[AuditLogger, Injected()],
       token: str,
   ) -> dict[str, str | int | None]:
       """Handle GET /user request."""
       auth.authenticate(token)
       user = user_service.get_current_user()
       print(f"  {audit.log('get_user')}")
       return user


   def main() -> None:
       container = Container()

       # RequestContext is shared within each request
       container.register(
           RequestContext,
           lifetime=Lifetime.SCOPED,
           scope=Scope.REQUEST,
       )
       # Services are transient but receive the scoped RequestContext
       container.register(AuthService)
       container.register(UserService)
       container.register(AuditLogger)

       # Create a scoped handler - each call gets its own scope
       handler = container.resolve(handle_get_user, scope=Scope.REQUEST)

       print("Simulating HTTP requests:\n")

       # Request 1
       print("Request 1 (valid token):")
       result1 = handler(token="valid-42")
       print(f"  Response: {result1}\n")

       # Request 2 (different scope, different context)
       print("Request 2 (invalid token):")
       result2 = handler(token="invalid")
       print(f"  Response: {result2}\n")

       # Request 3
       print("Request 3 (valid token, different user):")
       result3 = handler(token="valid-99")
       print(f"  Response: {result3}")


   if __name__ == "__main__":
       main()

Repository / unit-of-work pattern
---------------------------------

Demonstrates a repository pattern where the database session is shared within a
scope, and repositories are transient.

.. code-block:: python
   :class: diwire-example py-run

   import random
   from dataclasses import dataclass, field
   from enum import Enum
   from typing import Annotated

   from diwire import Container, Injected, Lifetime


   class Scope(str, Enum):
       """Application scope definitions."""

       UNIT_OF_WORK = "unit_of_work"


   @dataclass
   class Session:
       """Database session - shared within a unit of work."""

       session_id: int = field(default_factory=lambda: random.randint(1000, 9999))
       _pending_changes: list[str] = field(default_factory=list)

       def add(self, entity: str) -> None:
           self._pending_changes.append(f"INSERT {entity}")
           print(f"    [Session {self.session_id}] Staged: INSERT {entity}")

       def update(self, entity: str) -> None:
           self._pending_changes.append(f"UPDATE {entity}")
           print(f"    [Session {self.session_id}] Staged: UPDATE {entity}")

       def commit(self) -> None:
           print(f"    [Session {self.session_id}] Committing {len(self._pending_changes)} changes")
           self._pending_changes.clear()

       def rollback(self) -> None:
           print(f"    [Session {self.session_id}] Rolling back")
           self._pending_changes.clear()


   @dataclass
   class UserRepository:
       """Repository for User entities."""

       session: Session

       def create(self, name: str) -> str:
           self.session.add(f"User(name={name})")
           return f"User({name})"

       def update_email(self, user_id: int, email: str) -> None:
           self.session.update(f"User(id={user_id}, email={email})")


   @dataclass
   class OrderRepository:
       """Repository for Order entities."""

       session: Session

       def create(self, user_id: int, product: str) -> str:
           self.session.add(f"Order(user={user_id}, product={product})")
           return f"Order({product})"


   def create_user_with_order(
       user_repo: Annotated[UserRepository, Injected()],
       order_repo: Annotated[OrderRepository, Injected()],
       session: Annotated[Session, Injected()],
       username: str,
       product: str,
   ) -> dict[str, str]:
       """Create a user and their first order in a single unit of work."""
       user = user_repo.create(username)
       order = order_repo.create(user_id=1, product=product)
       session.commit()
       return {"user": user, "order": order}


   def main() -> None:
       container = Container()

       # Session is SCOPED - same session for entire unit of work
       container.register(
           Session,
           lifetime=Lifetime.SCOPED,
           scope=Scope.UNIT_OF_WORK,
       )
       # Repositories are transient but share the scoped session
       container.register(UserRepository)
       container.register(OrderRepository)

       # Create handler with automatic scope per call
       handler = container.resolve(create_user_with_order, scope=Scope.UNIT_OF_WORK)

       print("Repository pattern with scoped session:\n")

       # Unit of work 1
       print("Unit of Work 1:")
       result1 = handler(username="alice", product="Laptop")
       print(f"  Result: {result1}\n")

       # Unit of work 2 (new session)
       print("Unit of Work 2:")
       result2 = handler(username="bob", product="Phone")
       print(f"  Result: {result2}\n")

       # Manual scope management example
       print("Manual scope management:")
       with container.enter_scope(Scope.UNIT_OF_WORK) as scope:
           user_repo = scope.resolve(UserRepository)
           order_repo = scope.resolve(OrderRepository)
           session = scope.resolve(Session)

           # Both repos share the same session
           print(f"  Session: {session}")
           print(f"  UserRepository session: {user_repo.session.session_id}")
           print(f"  OrderRepository session: {order_repo.session.session_id}")
           print(f"  Same session: {user_repo.session is order_repo.session}")


   if __name__ == "__main__":
       main()

Class methods with container_context
------------------------------------

Demonstrates using ``container_context.resolve()`` decorator on class methods.
This pattern is useful for controller/handler classes where you want dependency
injection on instance methods.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass, field
   from typing import Annotated

   from diwire import Container, Injected, Lifetime, container_context


   @dataclass
   class Database:
       """Simulated database connection."""

       connection_id: str = field(default_factory=lambda: "db-001")

       def query(self, _sql: str) -> list[dict[str, str]]:
           # Simulated query - returns mock data
           return [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}]


   @dataclass
   class Logger:
       """Simple logger service."""

       def info(self, message: str) -> None:
           print(f"[INFO] {message}")


   @dataclass
   class Cache:
       """Simple cache service."""

       _data: dict[str, list[dict[str, str]]] = field(default_factory=dict)

       def get(self, key: str) -> list[dict[str, str]] | None:
           return self._data.get(key)

       def set(self, key: str, value: list[dict[str, str]]) -> None:
           self._data[key] = value


   class UserController:
       """Controller class with decorated instance methods.

       Each method uses container_context.resolve() to inject dependencies.
       The decorator properly binds 'self' so methods work as expected.
       """

       def __init__(self, prefix: str = "/api") -> None:
           self.prefix = prefix

       @container_context.resolve()
       def list_users(
           self,
           db: Annotated[Database, Injected()],
           logger: Annotated[Logger, Injected()],
       ) -> list[dict[str, str]]:
           """List all users - instance method with injected dependencies."""
           logger.info(f"{self.prefix}/users - Fetching all users")  # noqa: G004
           return db.query("SELECT * FROM users")

       @container_context.resolve()
       def get_user_cached(
           self,
           user_id: str,
           db: Annotated[Database, Injected()],
           cache: Annotated[Cache, Injected()],
           logger: Annotated[Logger, Injected()],
       ) -> dict[str, str] | None:
           """Get user with caching - shows mixing caller args with injected deps."""
           cache_key = f"user:{user_id}"

           cached = cache.get(cache_key)
           if cached:
               logger.info(f"{self.prefix}/users/{user_id} - Cache hit")  # noqa: G004
               return cached[0] if cached else None

           logger.info(f"{self.prefix}/users/{user_id} - Cache miss, querying DB")  # noqa: G004
           users = db.query(f"SELECT * FROM users WHERE id = {user_id}")
           if users:
               cache.set(cache_key, users)
               return users[0]
           return None


   def main() -> None:
       # Set up container
       container = Container()
       container.register(Database, lifetime=Lifetime.SINGLETON)
       container.register(Logger, lifetime=Lifetime.SINGLETON)
       container.register(Cache, lifetime=Lifetime.SINGLETON)

       # Set container in context
       token = container_context.set_current(container)

       try:
           # Create controller instance
           controller = UserController(prefix="/v1/api")

           print("=== Instance Method Decoration Example ===\n")

           # Call decorated instance method - 'self' is properly bound
           print("1. Calling list_users():")
           users = controller.list_users()
           print(f"   Result: {users}\n")

           # Call with caller-provided argument + injected dependencies
           print("2. Calling get_user_cached('1') - first call (cache miss):")
           user = controller.get_user_cached("1")
           print(f"   Result: {user}\n")

           print("3. Calling get_user_cached('1') - second call (cache hit):")
           user = controller.get_user_cached("1")
           print(f"   Result: {user}\n")

           # Demonstrate self.prefix is accessible
           print("4. Controller prefix is accessible in methods:")
           print(f"   controller.prefix = '{controller.prefix}'")

       finally:
           container_context.reset(token)


   if __name__ == "__main__":
       main()

Interface registration (Protocol/ABC -> concrete_class)
-------------------------------------------------------

Demonstrates how to program to interfaces/abstractions rather than concrete
implementations using diwire's ``concrete_class`` parameter.

.. code-block:: python
   :class: diwire-example py-run

   from abc import ABC, abstractmethod
   from typing import Protocol

   from diwire import Container, Lifetime


   # Define interfaces/abstractions
   class ILogger(Protocol):
       """Protocol for logging services."""

       def log(self, message: str) -> None: ...


   class IRepository(ABC):
       """Abstract base class for data repositories."""

       @abstractmethod
       def save(self, data: str) -> None: ...

       @abstractmethod
       def load(self) -> str: ...


   class IEmailService(ABC):
       """Abstract base class for email services."""

       @abstractmethod
       def send(self, to: str, subject: str, body: str) -> None: ...


   # Concrete implementations
   class ConsoleLogger:
       """Console-based logger implementation."""

       def log(self, message: str) -> None:
           print(f"[LOG] {message}")


   class FileRepository(IRepository):
       """File-based repository implementation."""

       def __init__(self, logger: ILogger) -> None:
           self.logger = logger
           self._data = ""

       def save(self, data: str) -> None:
           self.logger.log(f"Saving data: {data}")
           self._data = data

       def load(self) -> str:
           self.logger.log("Loading data")
           return self._data


   class SmtpEmailService(IEmailService):
       """SMTP-based email service implementation."""

       def __init__(self, logger: ILogger) -> None:
           self.logger = logger

       def send(self, to: str, subject: str, body: str) -> None:
           self.logger.log(f"Sending email to {to}: {subject}")


   # Application service that depends on interfaces
   class UserService:
       """User service that depends on abstract interfaces."""

       def __init__(
           self,
           repository: IRepository,
           email_service: IEmailService,
           logger: ILogger,
       ) -> None:
           self.repository = repository
           self.email_service = email_service
           self.logger = logger

       def create_user(self, username: str, email: str) -> None:
           self.logger.log(f"Creating user: {username}")
           self.repository.save(f"user:{username}")
           self.email_service.send(email, "Welcome!", f"Hello {username}!")


   def main() -> None:
       # Create container
       container = Container()

       # Register concrete implementations for interfaces
       # The key is the interface, 'concrete_class' specifies the implementation
       container.register(
           ILogger,
           concrete_class=ConsoleLogger,
           lifetime=Lifetime.SINGLETON,
       )

       container.register(
           IRepository,
           concrete_class=FileRepository,
           lifetime=Lifetime.SINGLETON,
       )

       container.register(
           IEmailService,
           concrete_class=SmtpEmailService,
           lifetime=Lifetime.SINGLETON,
       )

       # Resolve by interface type
       logger = container.resolve(ILogger)
       logger.log("Application starting...")

       # Resolve services that depend on interfaces
       user_service = container.resolve(UserService)
       user_service.create_user("john_doe", "john@example.com")

       # Verify the dependencies are properly injected
       repository = container.resolve(IRepository)
       print(f"Stored data: {repository.load()}")


   if __name__ == "__main__":
       main()
