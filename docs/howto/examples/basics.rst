.. meta::
   :description: diwire basics examples: registration methods, lifetimes, constructor injection, decorator registration, open generics, and compilation.

Basics
======

Registration methods
--------------------

Demonstrates three ways to register services:

#. Class registration - container creates instances
#. Factory registration - custom function creates instances
#. Instance registration - pre-created singleton

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass

   from diwire import Container


   @dataclass
   class Database:
       host: str
       port: int


   class Logger:
       def log(self, message: str) -> None:
           print(f"[LOG] {message}")


   class Cache:
       def __init__(self) -> None:
           self.data: dict[str, str] = {}


   def main() -> None:
       container = Container(autoregister=False)

       # 1. Simple class registration
       # Container will create instances using the class constructor
       container.register(Logger)
       logger = container.resolve(Logger)
       logger.log("Hello from registered class!")

       # 2. Factory registration
       # Use a factory function when you need custom instantiation logic
       def create_database() -> Database:
           return Database(host="localhost", port=5432)

       container.register(Database, factory=create_database)
       db = container.resolve(Database)
       print(f"Database: {db.host}:{db.port}")

       # 3. Instance registration
       # Register a pre-created object (always a singleton)
       cache_instance = Cache()
       cache_instance.data["key"] = "value"
       container.register(Cache, instance=cache_instance)

       resolved_cache = container.resolve(Cache)
       print(f"Cache data: {resolved_cache.data}")
       print(f"Same instance: {resolved_cache is cache_instance}")


   if __name__ == "__main__":
       main()

Lifetimes (TRANSIENT vs SINGLETON)
---------------------------------

Demonstrates the difference between:

- ``TRANSIENT``: new instance on every resolve
- ``SINGLETON``: same instance for entire container lifetime

.. code-block:: python
   :class: diwire-example py-run

   from diwire import Container, Lifetime


   class TransientService:
       """Created fresh on each resolution."""


   class SingletonService:
       """Shared across all resolutions."""


   def main() -> None:
       container = Container(autoregister=False)

       # TRANSIENT: new instance every time
       container.register(TransientService, lifetime=Lifetime.TRANSIENT)

       t1 = container.resolve(TransientService)
       t2 = container.resolve(TransientService)
       t3 = container.resolve(TransientService)

       print("TRANSIENT instances:")
       print(f"  t1 id: {id(t1)}")
       print(f"  t2 id: {id(t2)}")
       print(f"  t3 id: {id(t3)}")
       print(f"  All different: {t1 is not t2 is not t3}")

       # SINGLETON: same instance always
       container.register(SingletonService, lifetime=Lifetime.SINGLETON)

       s1 = container.resolve(SingletonService)
       s2 = container.resolve(SingletonService)
       s3 = container.resolve(SingletonService)

       print("\nSINGLETON instances:")
       print(f"  s1 id: {id(s1)}")
       print(f"  s2 id: {id(s2)}")
       print(f"  s3 id: {id(s3)}")
       print(f"  All same: {s1 is s2 is s3}")


   if __name__ == "__main__":
       main()

Constructor injection (auto-wiring)
-----------------------------------

Demonstrates automatic dependency resolution through constructor parameters.
The container analyzes type hints and injects dependencies automatically.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass
   from typing import Any

   from diwire import Container


   @dataclass
   class Config:
       """Application configuration."""

       database_url: str = "postgresql://localhost/app"
       debug: bool = True


   @dataclass
   class Database:
       """Database connection that depends on Config."""

       config: Config

       def query(self, sql: str, **kwargs: Any) -> str:
           return f"Executing on {self.config.database_url}: {sql.format(**kwargs)}"


   @dataclass
   class UserRepository:
       """Repository that depends on Database."""

       db: Database

       def find_user(self, user_id: int) -> str:
           return self.db.query("SELECT * FROM users WHERE id = {user_id}", user_id=user_id)


   @dataclass
   class UserService:
       """Service that depends on UserRepository."""

       repo: UserRepository

       def get_user_info(self, user_id: int) -> str:
           return f"User info: {self.repo.find_user(user_id)}"


   def main() -> None:
       container = Container()

       # Register Config with a specific instance
       container.register(Config, instance=Config(database_url="postgresql://prod/app"))

       # Resolve UserService - container automatically resolves entire chain:
       # UserService -> UserRepository -> Database -> Config
       service = container.resolve(UserService)

       result = service.get_user_info(42)
       print(result)

       # The entire dependency chain was resolved:
       print("\nDependency chain resolved:")
       print(f"  UserService has repo: {service.repo}")
       print(f"  UserRepository has db: {service.repo.db}")
       print(f"  Database has config: {service.repo.db.config}")


   if __name__ == "__main__":
       main()

Decorator registration
----------------------

Demonstrates using ``@container.register`` as a decorator for:

#. class registration (bare decorator or with explicit lifetime)
#. interface / protocol registration (``@container.register(Protocol, ...)``)
#. factory functions (sync / async) with dependency injection
#. scoped registrations (``lifetime=SCOPED`` + ``scope=...``)
#. staticmethod factories
#. generator-based cleanup (async generator factories)
#. ``container_context`` decorator registration

.. code-block:: python
   :class: diwire-example py-run

   import asyncio
   import uuid
   from collections.abc import AsyncGenerator
   from dataclasses import dataclass
   from typing import Protocol

   from diwire import Container, Lifetime, container_context


   # Define interfaces/protocols
   class IDatabase(Protocol):
       def query(self, sql: str) -> list[dict[str, str]]: ...


   class ILogger(Protocol):
       def log(self, message: str) -> None: ...


   # Create the container
   container = Container(autoregister=False)


   # Pattern 1: Bare class decorator (transient lifetime by default)
   @container.register
   class Config:
       def __init__(self) -> None:
           self.debug = True
           self.port = 8080


   # Pattern 2: Class decorator with lifetime parameter
   @container.register(lifetime=Lifetime.SINGLETON)
   class Logger:
       """A singleton logger."""

       def log(self, message: str) -> None:
           print(f"[LOG] {message}")


   # Pattern 3: Interface registration with @container.register(Interface, lifetime=...)
   # Note: A non-default keyword argument (e.g., SINGLETON) is required to use a type as decorator key
   @container.register(IDatabase, lifetime=Lifetime.SINGLETON)
   class PostgresDatabase:
       """Concrete database implementation registered as IDatabase interface."""

       def query(self, sql: str) -> list[dict[str, str]]:
           print(f"Executing: {sql}")
           return [{"result": "data"}]


   # Pattern 4: Factory function decorator (infers type from return annotation)
   class Cache:
       """A simple cache wrapper."""

       def __init__(self, data: dict[str, str]) -> None:
           self.data = data


   @container.register
   def create_cache() -> Cache:
       """Factory function that creates a cache."""
       return Cache({"initialized": "true"})


   # Pattern 5: Factory with explicit key (overrides return annotation)
   @dataclass
   class AppSettings:
       name: str
       version: str


   @container.register(AppSettings, lifetime=Lifetime.SINGLETON)
   def create_settings() -> AppSettings:
       return AppSettings(name="MyApp", version="1.0.0")


   # Pattern 6: Factory with auto-injected dependencies
   @dataclass
   class UserRepository:
       db: IDatabase
       logger: Logger


   @container.register
   def create_user_repository(db: IDatabase, logger: Logger) -> UserRepository:
       """Factory with dependencies that are automatically injected."""
       logger.log("Creating UserRepository")
       return UserRepository(db=db, logger=logger)


   # Pattern 7: Scoped with decorator
   @container.register(lifetime=Lifetime.SCOPED, scope="request")
   class RequestContext:
       """A request-scoped context object."""

       def __init__(self) -> None:
           self.request_id = str(uuid.uuid4())


   # Pattern 8: Async factory decorator
   @dataclass
   class AsyncService:
       initialized: bool


   @container.register(lifetime=Lifetime.SINGLETON)
   async def create_async_service() -> AsyncService:
       """Async factory that simulates async initialization."""
       # Simulate async initialization
       await asyncio.sleep(0)  # Simulated async work
       return AsyncService(initialized=True)


   # Pattern 9: Static method factory decorator
   class EmailService:
       """Email service created via static method factory."""

       def __init__(self, *, smtp_host: str) -> None:
           self.smtp_host = smtp_host

       def send(self, to: str, message: str) -> None:
           print(f"Sending email to {to} via {self.smtp_host}: {message}")


   class ConnectionPool:
       """A connection pool wrapper."""

       def __init__(self, connections: list[str]) -> None:
           self.connections = connections


   class ServiceFactories:
       """A collection of factory methods for creating services."""

       # Pattern 9a: Static method with bare decorator
       @staticmethod
       @container.register
       def create_email_service() -> EmailService:
           """Static method factory for EmailService."""
           return EmailService(smtp_host="smtp.example.com")

       # Pattern 9b: Static method with parameterized decorator
       @staticmethod
       @container.register(lifetime=Lifetime.SINGLETON)
       def create_connection_pool() -> ConnectionPool:
           """Static method factory that creates a singleton connection pool."""
           print("Creating connection pool...")
           return ConnectionPool(["conn1", "conn2", "conn3"])


   # Pattern 10: Async generator factory with cleanup
   class DatabaseConnection:
       def __init__(self) -> None:
           self.connected = True

       def close(self) -> None:
           self.connected = False


   @container.register(lifetime=Lifetime.SCOPED, scope="request")
   async def create_db_connection() -> AsyncGenerator[DatabaseConnection, None]:
       """Async generator factory with automatic cleanup."""
       conn = DatabaseConnection()
       print("Database connection opened")
       try:
           yield conn
       finally:
           conn.close()
           print("Database connection closed")


   def main() -> None:
       print("=== Decorator Registration Examples ===\n")

       # Resolve singleton logger
       logger1 = container.resolve(Logger)
       logger2 = container.resolve(Logger)
       logger1.log("Hello from logger!")
       print(f"Logger is singleton: {logger1 is logger2}\n")

       # Resolve interface (gets concrete implementation)
       db = container.resolve(IDatabase)
       db.query("SELECT * FROM users")
       print(f"Database type: {type(db).__name__}\n")

       # Resolve factory-created instances
       cache = container.resolve(Cache)
       print(f"Cache: {cache.data}\n")

       settings = container.resolve(AppSettings)
       print(f"Settings: {settings.name} v{settings.version}\n")

       # Resolve factory with dependencies
       repo = container.resolve(UserRepository)
       print(f"UserRepository has db: {repo.db is not None}")
       print(f"UserRepository has logger: {repo.logger is not None}\n")

       # Resolve scoped within a scope
       print("=== Scoped Demo ===")
       with container.enter_scope("request") as scope:
           ctx1 = scope.resolve(RequestContext)
           ctx2 = scope.resolve(RequestContext)
           print(f"Same request context: {ctx1 is ctx2}")
           print(f"Request ID: {ctx1.request_id}")

       print("\n=== Context Registration Demo ===")

       @container_context.register(lifetime=Lifetime.SINGLETON)
       class ContextLogger:
           """Logger registered via container_context decorator."""

           def log(self, message: str) -> None:
               print(f"[CTX] {message}")

       token = container_context.set_current(container)
       try:
           context_logger1 = container_context.resolve(ContextLogger)
           context_logger2 = container_context.resolve(ContextLogger)
           context_logger1.log("Hello from context logger!")
           print(f"Context logger is singleton: {context_logger1 is context_logger2}")
       finally:
           container_context.reset(token)

       # Demonstrate staticmethod factories
       print("\n=== Static Method Factory Demo ===")
       email_service = container.resolve(EmailService)
       email_service.send("user@example.com", "Hello!")

       conn_pool = container.resolve(ConnectionPool)
       print(f"Connection pool: {conn_pool.connections}")


   async def async_main() -> None:
       print("\n=== Async Factory Examples ===\n")

       # Resolve async factory
       async_service = await container.aresolve(AsyncService)
       print(f"Async service initialized: {async_service.initialized}")

       # Resolve async generator factory within scope
       print("\n=== Async Generator Factory with Cleanup ===")
       async with container.enter_scope("request") as scope:
           conn = await scope.aresolve(DatabaseConnection)
           print(f"Connection active: {conn.connected}")
       print(f"Connection after scope exit: {conn.connected}")


   if __name__ == "__main__":
       main()

       import asyncio

       asyncio.run(async_main())

Open generics
-------------

This example registers an open generic (``Box[T]``) and shows how diwire can resolve
different closed generic specializations (``Box[int]``, ``Box[str]``, ...).

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass
   from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

   from diwire import Container


   class Model:
       pass


   class User(Model):
       pass


   T = TypeVar("T")
   M = TypeVar("M", bound=Model)


   @dataclass
   class AnyBox(Generic[T]):
       value: str


   @dataclass
   class ModelBox(Generic[M]):
       model: M


   @dataclass
   class NonGenericModelBox:
       value: str


   container = Container()


   # Use TYPE_CHECKING guard to satisfy pyrefly while using TypeVars at runtime
   if TYPE_CHECKING:
       any_box_key: Any = AnyBox[Any]
       model_box_key: Any = ModelBox[Any]
   else:
       any_box_key = AnyBox[T]
       model_box_key = ModelBox[M]


   @cast("Any", container.register(any_box_key))
   def create_any_box(type_arg: type[T]) -> AnyBox[T]:
       return AnyBox(value=type_arg.__name__)


   @cast("Any", container.register(model_box_key))
   def create_model_box(model_cls: type[M]) -> ModelBox[M]:
       return ModelBox(model=model_cls())


   @cast("Any", container.register(NonGenericModelBox))
   def create_non_generic_model_box() -> NonGenericModelBox:
       return NonGenericModelBox(value="non-generic box")


   @cast("Any", container.register(AnyBox[float]))
   @cast("Any", container.register("LazyStringKey"))
   @dataclass
   class NonGenericModelBox2:
       value: str = "non-generic box 2"


   print(container.resolve(AnyBox[int]))
   print(container.resolve(AnyBox[str]))
   print(container.resolve(AnyBox[float]))  # should use NonGenericModelBox2
   print(container.resolve("LazyStringKey"))  # should use NonGenericModelBox2
   print(container.resolve(ModelBox[User]))
   print(container.resolve(NonGenericModelBox))
   print(container.resolve(NonGenericModelBox2))

Compilation
-----------

Demonstrates:

- manual compilation via ``container.compile()``
- disabling auto-compilation via ``Container(auto_compile=False)``

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass

   from diwire import Container, Lifetime


   @dataclass
   class ServiceA:
       value: str = "A"


   @dataclass
   class ServiceB:
       a: ServiceA


   def main() -> None:
       # Turn off auto-compilation so we can show the explicit call.
       container = Container(auto_compile=False)

       container.register(ServiceA, lifetime=Lifetime.SINGLETON)
       container.register(ServiceB, lifetime=Lifetime.TRANSIENT)

       # Works before compilation (reflection-based resolution).
       b1 = container.resolve(ServiceB)
       print(f"Before compile(): b1.a.value={b1.a.value!r}")

       # Precompute the dependency graph for maximum throughput.
       container.compile()

       b2 = container.resolve(ServiceB)
       print(f"After compile():  b2.a.value={b2.a.value!r}")

       # Transient behavior is unchanged: new ServiceB each time.
       print(f"Transient preserved: {b1 is not b2}")

       # Singleton behavior is unchanged: same ServiceA.
       print(f"Singleton preserved: {b1.a is b2.a}")


   if __name__ == "__main__":
       main()

