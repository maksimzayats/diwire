"""Async function-injection deep dive.

This focused script covers async callables using ``Injected[T]`` and caller
overrides for injected async parameters.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from diwire import Container, Injected, resolver_context


@dataclass(slots=True)
class AsyncUser:
    email: str


async def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(AsyncUser(email="async@example.com"))

    @resolver_context.inject
    async def handler(user: Injected[AsyncUser]) -> str:
        return user.email

    default_value = await handler()
    overridden_value = await handler(user=AsyncUser(email="override@example.com"))

    if default_value != "async@example.com":
        msg = "Unexpected default async injection result"
        raise TypeError(msg)
    if overridden_value != "override@example.com":
        msg = "Unexpected async override injection result"
        raise TypeError(msg)


if __name__ == "__main__":
    asyncio.run(main())
