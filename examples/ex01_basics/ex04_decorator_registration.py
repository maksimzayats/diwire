"""Decorator-Based Registration in DIWire.

Demonstrates using @container.register as a decorator for:
1. Class registration with automatic or custom lifetimes
2. Factory function registration with type inference
3. Interface/Protocol registration via provides parameter
4. Async factory function registration
5. Factory functions with auto-injected dependencies
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol

from diwire import Container, Lifetime


# Define interfaces/protocols
class IDatabase(Protocol):
    def query(self, sql: str) -> list[dict[str, str]]: ...


class ILogger(Protocol):
    def log(self, message: str) -> None: ...


# Create the container
container = Container(register_if_missing=False)


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


# Pattern 3: Interface registration with provides parameter
@container.register(provides=IDatabase)
class PostgresDatabase:
    """Concrete database implementation registered as IDatabase interface."""

    def query(self, sql: str) -> list[dict[str, str]]:
        print(f"Executing: {sql}")
        return [{"result": "data"}]


# Pattern 4: Factory function decorator (infers type from return annotation)
@container.register
def create_cache() -> dict[str, str]:
    """Factory function that creates a cache dictionary."""
    return {"initialized": "true"}


# Pattern 5: Factory with explicit provides (overrides return annotation)
@dataclass
class AppSettings:
    name: str
    version: str


@container.register(provides=AppSettings, lifetime=Lifetime.SINGLETON)
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


# Pattern 7: Scoped singleton with decorator
@container.register(lifetime=Lifetime.SCOPED_SINGLETON, scope="request")
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


# Pattern 9: Async generator factory with cleanup
class DatabaseConnection:
    def __init__(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    @staticmethod
    @container.register(lifetime=Lifetime.SCOPED_SINGLETON, scope="request")
    async def create_db_connection() -> AsyncGenerator["DatabaseConnection", None]:
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
    cache = container.resolve(dict)
    print(f"Cache: {cache}\n")

    settings = container.resolve(AppSettings)
    print(f"Settings: {settings.name} v{settings.version}\n")

    # Resolve factory with dependencies
    repo = container.resolve(UserRepository)
    print(f"UserRepository has db: {repo.db is not None}")
    print(f"UserRepository has logger: {repo.logger is not None}\n")

    # Resolve scoped singleton within a scope
    print("=== Scoped Singleton Demo ===")
    with container.start_scope("request") as scope:
        ctx1 = scope.resolve(RequestContext)
        ctx2 = scope.resolve(RequestContext)
        print(f"Same request context: {ctx1 is ctx2}")
        print(f"Request ID: {ctx1.request_id}")


async def async_main() -> None:
    print("\n=== Async Factory Examples ===\n")

    # Resolve async factory
    async_service = await container.aresolve(AsyncService)
    print(f"Async service initialized: {async_service.initialized}")

    # Resolve async generator factory within scope
    print("\n=== Async Generator Factory with Cleanup ===")
    async with container.start_scope("request") as scope:
        conn = await scope.aresolve(DatabaseConnection)
        print(f"Connection active: {conn.connected}")
    print(f"Connection after scope exit: {conn.connected}")


if __name__ == "__main__":
    main()

    import asyncio

    asyncio.run(async_main())
