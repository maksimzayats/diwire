"""Error handling with async dependencies.

Demonstrates:
1. DIWireAsyncDependencyInSyncContextError - when sync resolve() hits async dep
2. DIWireAsyncGeneratorFactoryWithoutScopeError - async gen without scope
3. Proper error handling patterns
"""

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
