"""Decorator-Based Registration in DIWire.

Demonstrates using @container.register as a decorator for:
1. Class registration with automatic or custom lifetimes
2. Factory function registration with type inference
3. Interface/Protocol registration via @container.register(Interface)
4. Factory functions with auto-injected dependencies
5. Scoped decorator usage
6. Async factory function registration
7. Static method factories
8. Async generator factories with cleanup
9. container_context decorator registration
"""

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


# Pattern 10: Async generator factory with cleanup (using staticmethod)
class DatabaseConnection:
    def __init__(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False


# Note: Factory defined outside class to avoid forward reference issues
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
