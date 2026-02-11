"""Async factories, async cleanup, and async resolution.

This module demonstrates:

1. ``add_factory()`` with an ``async def`` factory + ``await container.aresolve(...)``.
2. ``add_generator()`` with an async generator + ``async with container.enter_scope(...)`` cleanup.
3. The sync/async boundary: resolving an async graph via ``resolve()`` raises an error.
"""

from __future__ import annotations

import asyncio

from diwire import Container, Lifetime, Scope
from diwire.exceptions import DIWireAsyncDependencyInSyncContextError


class AsyncService:
    def __init__(self, value: str) -> None:
        self.value = value


class AsyncResource:
    pass


async def main() -> None:
    container = Container(autoregister_concrete_types=False)

    async def build_async_service() -> AsyncService:
        await asyncio.sleep(0)
        return AsyncService(value="ok")

    container.add_factory(build_async_service, provides=AsyncService)

    service = await container.aresolve(AsyncService)
    print(f"async_factory_value={service.value}")  # => async_factory_value=ok

    try:
        container.resolve(AsyncService)
    except DIWireAsyncDependencyInSyncContextError as error:
        async_in_sync = type(error).__name__
    print(
        f"async_in_sync={async_in_sync}",
    )  # => async_in_sync=DIWireAsyncDependencyInSyncContextError

    state = {"opened": 0, "closed": 0}

    async def provide_async_resource():
        state["opened"] += 1
        try:
            yield AsyncResource()
        finally:
            await asyncio.sleep(0)
            state["closed"] += 1

    container.add_generator(
        provide_async_resource,
        provides=AsyncResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    async with container.enter_scope() as request_scope:
        _ = await request_scope.aresolve(AsyncResource)
        closed_before_exit = state["closed"]

    async_cleanup_after_exit = closed_before_exit == 0 and state["closed"] == 1
    print(
        f"async_cleanup_after_exit={async_cleanup_after_exit}",
    )  # => async_cleanup_after_exit=True


if __name__ == "__main__":
    asyncio.run(main())
