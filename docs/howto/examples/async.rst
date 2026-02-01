.. meta::
   :description: diwire async examples: aresolve(), async factories, async generator cleanup, async function injection, scoped async injection, parallel resolution, and FastAPI-style patterns.

Async
=====

Basic async factory
-------------------

Demonstrates how to register and resolve services with async factories.
Async factories are auto-detected (no special configuration needed).

.. code-block:: python
   :class: diwire-example py-run

   import asyncio

   from diwire import Container, Lifetime


   # Simulated async database connection
   class Database:
       def __init__(self, connection_string: str):
           self.connection_string = connection_string
           self.connected = False

       async def connect(self) -> None:
           # Simulate async connection
           await asyncio.sleep(0.01)
           self.connected = True

       async def query(self, sql: str) -> list[dict]:
           if not self.connected:
               raise RuntimeError("Not connected")
           await asyncio.sleep(0.01)
           return [{"id": 1, "name": "Example"}]


   # Async factory function - automatically detected as async
   async def create_database() -> Database:
       """Async factory that creates and connects a database."""
       db = Database("postgresql://localhost/mydb")
       await db.connect()
       return db


   async def main() -> None:
       container = Container()

       # Register with async factory - is_async is auto-detected
       container.register(Database, factory=create_database, lifetime=Lifetime.SINGLETON)

       # Must use aresolve() for async dependencies
       db = await container.aresolve(Database)
       print(f"Database connected: {db.connected}")

       # Query the database
       results = await db.query("SELECT * FROM users")
       print(f"Query results: {results}")

       # Singleton behavior works the same - same instance returned
       db2 = await container.aresolve(Database)
       print(f"Same instance: {db is db2}")


   if __name__ == "__main__":
       asyncio.run(main())

Async generator cleanup
-----------------------

Demonstrates how async generators can be used for resource lifecycle management.
The cleanup code in the ``finally`` block runs automatically when the scope exits.

.. code-block:: python
   :class: diwire-example py-run

   import asyncio

   from diwire import Container, Lifetime


   class DatabaseSession:
       """Represents a database session that needs cleanup."""

       def __init__(self, session_id: str):
           self.session_id = session_id
           self.closed = False

       async def execute(self, query: str) -> list[dict]:
           if self.closed:
               raise RuntimeError("Session is closed")
           await asyncio.sleep(0.01)
           return [{"result": f"executed: {query}"}]

       async def close(self) -> None:
           print(f"  Closing session {self.session_id}")
           await asyncio.sleep(0.01)
           self.closed = True


   # Async generator factory - cleanup runs in finally block
   async def create_session():
       """Async generator factory with automatic cleanup.

       The code before yield creates the resource.
       The code in finally runs when the scope exits.
       """
       session = DatabaseSession("session-123")
       print(f"  Created session {session.session_id}")
       try:
           yield session
       finally:
           # This runs automatically when the scope exits
           await session.close()


   async def main() -> None:
       container = Container()

       # Register async generator with scope
       container.register(
           DatabaseSession,
           factory=create_session,
           lifetime=Lifetime.SCOPED,
           scope="request",
       )

       print("Starting request scope...")

       # Use async context manager for proper cleanup
       async with container.enter_scope("request"):
           session = await container.aresolve(DatabaseSession)
           print(f"  Got session: {session.session_id}")

           # Use the session
           results = await session.execute("SELECT * FROM users")
           print(f"  Query results: {results}")

           # Same session within scope
           session2 = await container.aresolve(DatabaseSession)
           print(f"  Same session: {session is session2}")

       # Session is automatically closed when scope exits
       print("Request scope ended.")
       print(f"Session closed: {session.closed}")


   if __name__ == "__main__":
       asyncio.run(main())

Async injected functions
------------------------

Demonstrates how to use ``Injected`` with async functions.
The resolved function becomes an ``AsyncInjectedFunction`` wrapper that resolves
dependencies on each call.

.. code-block:: python
   :class: diwire-example py-run

   import asyncio
   from typing import Annotated

   from diwire import Container, Injected, Lifetime


   # Services
   class UserRepository:
       async def get_user(self, user_id: int) -> dict:
           await asyncio.sleep(0.01)
           return {"id": user_id, "name": f"User {user_id}"}


   class EmailService:
       async def send_email(self, to: str, subject: str) -> bool:
           await asyncio.sleep(0.01)
           print(f"    Sent email to {to}: {subject}")
           return True


   class Logger:
       def log(self, message: str) -> None:
           print(f"    [LOG] {message}")


   # Async handler function with injected dependencies
   async def get_user_handler(
       user_repo: Annotated[UserRepository, Injected()],
       logger: Annotated[Logger, Injected()],
       user_id: int,  # Regular parameter - not injected
   ) -> dict:
       """Async handler with mixed injected and regular parameters."""
       logger.log(f"Fetching user {user_id}")
       user = await user_repo.get_user(user_id)
       logger.log(f"Found user: {user['name']}")
       return user


   async def send_welcome_email(
       user_repo: Annotated[UserRepository, Injected()],
       email_service: Annotated[EmailService, Injected()],
       user_id: int,
   ) -> bool:
       """Another async handler demonstrating multiple async deps."""
       user = await user_repo.get_user(user_id)
       return await email_service.send_email(
           to=f"{user['name'].lower().replace(' ', '.')}@example.com",
           subject="Welcome!",
       )


   async def main() -> None:
       container = Container()

       # Register services
       container.register(UserRepository, lifetime=Lifetime.SINGLETON)
       container.register(EmailService, lifetime=Lifetime.SINGLETON)
       container.register(Logger, lifetime=Lifetime.SINGLETON)

       # Resolve async function - returns AsyncInjectedFunction wrapper
       get_user = await container.aresolve(get_user_handler)
       print(f"Resolved handler type: {type(get_user)}")

       # Call the injected function - dependencies resolved automatically
       print("\nCalling get_user_handler(user_id=42):")
       user = await get_user(user_id=42)
       print(f"  Result: {user}")

       # Resolve and call another handler
       send_email = await container.aresolve(send_welcome_email)
       print("\nCalling send_welcome_email(user_id=42):")
       success = await send_email(user_id=42)
       print(f"  Success: {success}")

       # The injected function's signature excludes Injected params
       import inspect

       sig = inspect.signature(get_user)
       print(f"\nInjected function signature: {sig}")
       print("  (Injected parameters are hidden from the signature)")


   if __name__ == "__main__":
       asyncio.run(main())

Async scoped injection
----------------------

Demonstrates ``AsyncScopedInjected``: resolving an async function whose dependencies
include scoped services creates a new scope per invocation.

.. code-block:: python
   :class: diwire-example py-run

   import asyncio
   from typing import Annotated

   from diwire import Container, Injected, Lifetime


   class RequestContext:
       """Per-request context with unique ID."""

       _counter = 0

       def __init__(self):
           RequestContext._counter += 1
           self.request_id = f"req-{RequestContext._counter}"
           print(f"    Created {self.request_id}")

       def __repr__(self) -> str:
           return f"RequestContext({self.request_id})"


   class DatabaseTransaction:
       """Simulated database transaction tied to request scope."""

       def __init__(self, context: RequestContext):
           self.context = context
           self.committed = False
           self.rolled_back = False
           print(f"    Created transaction for {context.request_id}")


   # Async generator for transaction with cleanup
   async def create_transaction(context: RequestContext):
       """Creates a transaction that auto-commits or rolls back."""
       tx = DatabaseTransaction(context)
       try:
           yield tx
           # If we get here without exception, commit
           print(f"    Committing transaction for {context.request_id}")
           tx.committed = True
       except Exception:
           print(f"    Rolling back transaction for {context.request_id}")
           tx.rolled_back = True
           raise


   # Request handler - gets scoped dependencies
   async def handle_request(
       context: Annotated[RequestContext, Injected()],
       transaction: Annotated[DatabaseTransaction, Injected()],
       data: dict,
   ) -> dict:
       """Handler that uses scoped dependencies.

       Each call gets its own RequestContext and DatabaseTransaction.
       """
       print(f"    Processing request {context.request_id} with data: {data}")
       await asyncio.sleep(0.01)  # Simulate async work
       return {
           "request_id": context.request_id,
           "status": "success",
           "data": data,
       }


   async def main() -> None:
       container = Container()

       # Register scoped dependencies
       container.register(
           RequestContext,
           lifetime=Lifetime.SCOPED,
           scope="request",
       )
       container.register(
           DatabaseTransaction,
           factory=create_transaction,
           lifetime=Lifetime.SCOPED,
           scope="request",
       )

       # Resolve function with scoped deps - returns AsyncScopedInjected
       handler = await container.aresolve(handle_request)
       print(f"Handler type: {type(handler)}")

       # Each call creates a new scope with fresh dependencies
       print("\n--- First request ---")
       result1 = await handler(data={"action": "create", "item": "foo"})
       print(f"Result: {result1}")

       print("\n--- Second request ---")
       result2 = await handler(data={"action": "update", "item": "bar"})
       print(f"Result: {result2}")

       # Notice: different request IDs for each call
       print(f"\nDifferent request IDs: {result1['request_id']} vs {result2['request_id']}")

       # Concurrent requests each get their own scope
       print("\n--- Concurrent requests ---")

       async def make_request(n: int) -> dict:
           return await handler(data={"request_number": n})

       results = await asyncio.gather(
           make_request(1),
           make_request(2),
           make_request(3),
       )

       print("\nConcurrent results:")
       for r in results:
           print(f"  {r['request_id']}: {r['data']}")


   if __name__ == "__main__":
       asyncio.run(main())

Mixed sync/async + parallel resolution
--------------------------------------

Demonstrates:

#. Services with both sync and async dependencies
#. Automatic parallel resolution of multiple async deps via ``asyncio.gather()``
#. Performance benefits of parallel resolution

.. code-block:: python
   :class: diwire-example py-run

   import asyncio
   import time

   from diwire import Container, Lifetime


   # Sync service - no async needed
   class Config:
       def __init__(self):
           self.db_url = "postgresql://localhost/mydb"
           self.cache_url = "redis://localhost:6379"
           self.api_key = "secret-key"


   # Async services that take time to initialize
   class DatabasePool:
       def __init__(self):
           self.pool_size = 0

       async def initialize(self) -> None:
           await asyncio.sleep(0.05)  # Simulate connection pool creation
           self.pool_size = 10


   class CacheClient:
       def __init__(self):
           self.connected = False

       async def connect(self) -> None:
           await asyncio.sleep(0.05)  # Simulate cache connection
           self.connected = True


   class ExternalAPIClient:
       def __init__(self):
           self.authenticated = False

       async def authenticate(self) -> None:
           await asyncio.sleep(0.05)  # Simulate API authentication
           self.authenticated = True


   # Async factory classes with __call__ method
   class DatabasePoolFactory:
       async def __call__(self) -> DatabasePool:
           pool = DatabasePool()
           await pool.initialize()
           return pool


   class CacheClientFactory:
       async def __call__(self) -> CacheClient:
           client = CacheClient()
           await client.connect()
           return client


   class ExternalAPIClientFactory:
       async def __call__(self) -> ExternalAPIClient:
           client = ExternalAPIClient()
           await client.authenticate()
           return client


   # Service that depends on all three async services
   class ApplicationService:
       """Service with multiple async dependencies - resolved in parallel."""

       def __init__(
           self,
           config: Config,  # Sync dependency
           db: DatabasePool,  # Async dependency
           cache: CacheClient,  # Async dependency
           api: ExternalAPIClient,  # Async dependency
       ):
           self.config = config
           self.db = db
           self.cache = cache
           self.api = api

       def status(self) -> dict:
           return {
               "db_pool_size": self.db.pool_size,
               "cache_connected": self.cache.connected,
               "api_authenticated": self.api.authenticated,
           }


   async def main() -> None:
       container = Container()

       # Register sync config
       container.register(Config, lifetime=Lifetime.SINGLETON)

       # Register async factory classes (auto-detected as async)
       container.register(DatabasePoolFactory, lifetime=Lifetime.SINGLETON)
       container.register(CacheClientFactory, lifetime=Lifetime.SINGLETON)
       container.register(ExternalAPIClientFactory, lifetime=Lifetime.SINGLETON)

       # Register services with async factory classes
       container.register(DatabasePool, factory=DatabasePoolFactory, lifetime=Lifetime.SINGLETON)
       container.register(CacheClient, factory=CacheClientFactory, lifetime=Lifetime.SINGLETON)
       container.register(
           ExternalAPIClient,
           factory=ExternalAPIClientFactory,
           lifetime=Lifetime.SINGLETON,
       )

       # Register the service that depends on all of them
       container.register(ApplicationService, lifetime=Lifetime.SINGLETON)

       print("Resolving ApplicationService with 3 async dependencies...")
       print("Each async factory takes ~50ms to complete.\n")

       # Measure resolution time
       start = time.perf_counter()
       service = await container.aresolve(ApplicationService)
       elapsed = time.perf_counter() - start

       print(f"Resolution completed in {elapsed:.3f} seconds")
       print(f"Service status: {service.status()}")

       # If resolved sequentially: ~150ms (3 x 50ms)
       # If resolved in parallel: ~50ms
       if elapsed < 0.1:
           print("\n[OK] Dependencies were resolved in PARALLEL!")
           print("    (3 x 50ms deps completed in ~50ms total)")
       else:
           print("\n[!] Dependencies were resolved sequentially")

       # Demonstrate that subsequent resolves are instant (cached singletons)
       print("\n--- Second resolution (cached) ---")
       start = time.perf_counter()
       service2 = await container.aresolve(ApplicationService)
       elapsed = time.perf_counter() - start
       print(f"Second resolution: {elapsed * 1000:.2f}ms (cached singleton)")
       print(f"Same instance: {service is service2}")


   if __name__ == "__main__":
       asyncio.run(main())

Async error handling
--------------------

Demonstrates:

#. ``DIWireAsyncDependencyInSyncContextError`` - when sync ``resolve()`` hits an async dependency
#. ``DIWireAsyncGeneratorFactoryWithoutScopeError`` - using an async generator without a scope
#. recommended error handling patterns

.. code-block:: python
   :class: diwire-example py-run

   import asyncio

   from diwire import Container, Lifetime
   from diwire.exceptions import (
       DIWireAsyncDependencyInSyncContextError,
       DIWireAsyncGeneratorFactoryWithoutScopeError,
   )


   class AsyncDatabase:
       """Database that requires async initialization."""


   async def create_async_db() -> AsyncDatabase:
       await asyncio.sleep(0.01)
       return AsyncDatabase()


   async def session_factory():
       """Async generator factory that requires a scope."""
       yield "session"


   def demonstrate_sync_resolve_error() -> None:
       """Shows what happens when you try sync resolve() on async dependency."""
       print("--- DIWireAsyncDependencyInSyncContextError ---\n")

       container = Container()
       container.register(AsyncDatabase, factory=create_async_db)

       print("Registered AsyncDatabase with async factory.")
       print("Attempting container.resolve(AsyncDatabase)...\n")

       try:
           # This will fail because the factory is async
           container.resolve(AsyncDatabase)
       except DIWireAsyncDependencyInSyncContextError as e:
           print(f"Caught: {type(e).__name__}")
           print(f"Message: {e}")
           print("\nSolution: Use 'await container.aresolve(AsyncDatabase)' instead")


   async def demonstrate_async_gen_without_scope() -> None:
       """Shows error when async generator factory is used without scope."""
       print("\n--- DIWireAsyncGeneratorFactoryWithoutScopeError ---\n")

       container = Container()

       # Register async generator WITHOUT a scope
       container.register(
           "Session",
           factory=session_factory,
           lifetime=Lifetime.TRANSIENT,  # No scope specified
       )

       print("Registered async generator factory without scope.")
       print("Attempting await container.aresolve('Session')...\n")

       try:
           # This will fail because async generators need a scope for cleanup
           await container.aresolve("Session")
       except DIWireAsyncGeneratorFactoryWithoutScopeError as e:
           print(f"Caught: {type(e).__name__}")
           print(f"Message: {e}")
           print(
               "\nSolution: Register with scope='request' and use 'async with container.enter_scope()'",
           )


   async def demonstrate_proper_usage() -> None:
       """Shows the correct way to handle async dependencies."""
       print("\n--- Correct Usage ---\n")

       container = Container()

       # 1. Async factory - use aresolve()
       container.register(AsyncDatabase, factory=create_async_db, lifetime=Lifetime.SINGLETON)

       print("1. Resolving async factory correctly:")
       db = await container.aresolve(AsyncDatabase)
       print(f"   Got: {db}")

       # 2. Async generator - use with scope
       container.register(
           "Session",
           factory=session_factory,
           lifetime=Lifetime.SCOPED,
           scope="request",
       )

       print("\n2. Resolving async generator with scope:")
       async with container.enter_scope("request"):
           session = await container.aresolve("Session")
           print(f"   Got: {session}")
       print("   (Cleanup runs automatically on scope exit)")


   async def demonstrate_detecting_async_deps() -> None:
       """Shows how to check if a dependency is async before resolving."""
       print("\n--- Detecting Async Dependencies ---\n")

       container = Container()
       container.register(AsyncDatabase, factory=create_async_db)
       container.register(str, instance="sync_value")

       from diwire.service_key import ServiceKey

       def is_async_registered(container: Container, key) -> bool:
           """Check if a key is registered with an async factory."""
           service_key = ServiceKey.from_value(key)
           reg = container._registry.get(service_key)
           return reg is not None and reg.is_async

       print(f"AsyncDatabase is async: {is_async_registered(container, AsyncDatabase)}")
       print(f"str is async: {is_async_registered(container, str)}")

       # Choose resolve method based on registration
       if is_async_registered(container, AsyncDatabase):
           db = await container.aresolve(AsyncDatabase)
       else:
           db = container.resolve(AsyncDatabase)

       print(f"\nResolved correctly: {db}")


   async def main() -> None:
       demonstrate_sync_resolve_error()
       await demonstrate_async_gen_without_scope()
       await demonstrate_proper_usage()
       await demonstrate_detecting_async_deps()


   if __name__ == "__main__":
       asyncio.run(main())

FastAPI-style async pattern
---------------------------

Demonstrates a realistic usage pattern similar to how you'd use async DI in a
FastAPI (or similar) async web framework: per-request scopes, async generator
cleanup, and injected request handlers.

.. code-block:: python
   :class: diwire-example py-run

   import asyncio
   from dataclasses import dataclass
   from typing import Annotated

   from diwire import Container, Injected, Lifetime

   # =============================================================================
   # Domain Models
   # =============================================================================


   @dataclass
   class User:
       id: int
       email: str
       name: str


   @dataclass
   class Order:
       id: int
       user_id: int
       total: float
       status: str


   # =============================================================================
   # Repository Layer (async database access)
   # =============================================================================


   class UserRepository:
       """Simulated async user repository."""

       _users = {
           1: User(1, "alice@example.com", "Alice"),
           2: User(2, "bob@example.com", "Bob"),
       }

       async def get_by_id(self, user_id: int) -> User | None:
           await asyncio.sleep(0.01)  # Simulate DB query
           return self._users.get(user_id)

       async def get_by_email(self, email: str) -> User | None:
           await asyncio.sleep(0.01)
           for user in self._users.values():
               if user.email == email:
                   return user
           return None


   class OrderRepository:
       """Simulated async order repository."""

       _orders = {
           1: Order(1, 1, 99.99, "completed"),
           2: Order(2, 1, 149.50, "pending"),
           3: Order(3, 2, 75.00, "completed"),
       }

       async def get_by_user(self, user_id: int) -> list[Order]:
           await asyncio.sleep(0.01)
           return [o for o in self._orders.values() if o.user_id == user_id]


   # =============================================================================
   # Service Layer
   # =============================================================================


   class UserService:
       def __init__(self, user_repo: UserRepository):
           self.user_repo = user_repo

       async def get_user(self, user_id: int) -> User | None:
           return await self.user_repo.get_by_id(user_id)


   class OrderService:
       def __init__(self, order_repo: OrderRepository, user_repo: UserRepository):
           self.order_repo = order_repo
           self.user_repo = user_repo

       async def get_user_orders(self, user_id: int) -> dict:
           # Parallel fetch of user and orders
           user_task = self.user_repo.get_by_id(user_id)
           orders_task = self.order_repo.get_by_user(user_id)

           user, orders = await asyncio.gather(user_task, orders_task)

           if user is None:
               return {"error": "User not found"}

           return {
               "user": {"id": user.id, "name": user.name, "email": user.email},
               "orders": [{"id": o.id, "total": o.total, "status": o.status} for o in orders],
               "total_spent": sum(o.total for o in orders if o.status == "completed"),
           }


   # =============================================================================
   # Database Session (scoped, with cleanup)
   # =============================================================================


   class DatabaseSession:
       """Per-request database session with transaction support."""

       _counter = 0

       def __init__(self):
           DatabaseSession._counter += 1
           self.session_id = DatabaseSession._counter
           self.in_transaction = False

       async def begin(self) -> None:
           self.in_transaction = True

       async def commit(self) -> None:
           await asyncio.sleep(0.005)
           self.in_transaction = False

       async def rollback(self) -> None:
           await asyncio.sleep(0.005)
           self.in_transaction = False

       async def close(self) -> None:
           if self.in_transaction:
               await self.rollback()


   async def create_db_session():
       """Async generator factory for database session."""
       session = DatabaseSession()
       await session.begin()
       try:
           yield session
           await session.commit()
       except Exception:
           await session.rollback()
           raise
       finally:
           await session.close()


   # =============================================================================
   # Request Handlers (with Injected injection)
   # =============================================================================


   async def get_user_handler(
       user_service: Annotated[UserService, Injected()],
       session: Annotated[DatabaseSession, Injected()],
       user_id: int,
   ) -> dict:
       """Handler to get a single user."""
       print(f"  [Session {session.session_id}] Getting user {user_id}")
       user = await user_service.get_user(user_id)
       if user is None:
           return {"error": "User not found"}
       return {"id": user.id, "name": user.name, "email": user.email}


   async def get_user_orders_handler(
       order_service: Annotated[OrderService, Injected()],
       session: Annotated[DatabaseSession, Injected()],
       user_id: int,
   ) -> dict:
       """Handler to get user with their orders."""
       print(f"  [Session {session.session_id}] Getting orders for user {user_id}")
       return await order_service.get_user_orders(user_id)


   # =============================================================================
   # Application Setup
   # =============================================================================


   def create_container() -> Container:
       """Configure the DI container for the application."""
       container = Container()

       # Repositories - singleton (shared connection pool in real app)
       container.register(UserRepository, lifetime=Lifetime.SINGLETON)
       container.register(OrderRepository, lifetime=Lifetime.SINGLETON)

       # Services - singleton (stateless)
       container.register(UserService, lifetime=Lifetime.SINGLETON)
       container.register(OrderService, lifetime=Lifetime.SINGLETON)

       # Database session - scoped per request with cleanup
       container.register(
           DatabaseSession,
           factory=create_db_session,
           lifetime=Lifetime.SCOPED,
           scope="request",
       )

       return container


   # =============================================================================
   # Simulated Request Handling
   # =============================================================================


   async def handle_request(container: Container, handler, **kwargs) -> dict:
       """Simulate handling an HTTP request."""
       # Each request gets its own scope
       async with container.enter_scope("request"):
           # Resolve the handler (gets AsyncScopedInjected due to scoped deps)
           injected_handler = await container.aresolve(handler)
           return await injected_handler(**kwargs)


   async def main() -> None:
       container = create_container()

       print("=== FastAPI-Style Async DI Demo ===\n")

       # Simulate concurrent requests
       print("Processing concurrent requests...\n")

       results = await asyncio.gather(
           handle_request(container, get_user_handler, user_id=1),
           handle_request(container, get_user_orders_handler, user_id=1),
           handle_request(container, get_user_handler, user_id=2),
           handle_request(container, get_user_orders_handler, user_id=2),
           handle_request(container, get_user_handler, user_id=999),  # Not found
       )

       print("\n--- Results ---")
       for i, result in enumerate(results, 1):
           print(f"Request {i}: {result}")


   if __name__ == "__main__":
       asyncio.run(main())

