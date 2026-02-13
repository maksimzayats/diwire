"""Focused example: async-generator provider cleanup on async scope exit."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from diwire import Container, Lifetime, Scope


class AsyncResource:
    pass


async def main() -> None:
    container = Container()
    state = {"closed": 0}

    async def provide_async_resource() -> AsyncGenerator[AsyncResource, None]:
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

    print(
        f"async_cleanup_after_exit={closed_before_exit == 0 and state['closed'] == 1}",
    )  # => async_cleanup_after_exit=True


if __name__ == "__main__":
    asyncio.run(main())
