"""Mixed sync/async dependencies and parallel resolution.

Demonstrates:
1. Services with both sync and async dependencies
2. Automatic parallel resolution of multiple async deps via asyncio.gather()
3. Performance benefits of parallel resolution
"""

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
