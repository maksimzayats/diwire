"""Focused example: async factory registration with ``await container.aresolve(...)``."""

from __future__ import annotations

import asyncio

from diwire import Container


class AsyncService:
    def __init__(self, value: str) -> None:
        self.value = value


async def main() -> None:
    container = Container(autoregister_concrete_types=False)

    async def build_async_service() -> AsyncService:
        await asyncio.sleep(0)
        return AsyncService(value="ok")

    container.add_factory(build_async_service, provides=AsyncService)

    service = await container.aresolve(AsyncService)
    print(f"async_factory_value={service.value}")  # => async_factory_value=ok


if __name__ == "__main__":
    asyncio.run(main())
