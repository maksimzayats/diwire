"""Return a borrowed connection when an async job is cancelled.

Cancel once and await the task. The job owns its request scope, so async
cleanup finishes before the caller receives CancelledError. This in-memory
connection needs no database or network service.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from diwire import Container, Lifetime, Scope


@dataclass
class Connection:
    events: list[str]
    released: bool = False

    async def release(self) -> None:
        self.events.append("release:start")
        # A real driver would await its connection release operation here.
        await asyncio.sleep(0)
        self.released = True
        self.events.append("release:done")


def create_container(events: list[str]) -> Container:
    container = Container()

    async def borrow_connection() -> AsyncGenerator[Connection, None]:
        connection = Connection(events)
        events.append("acquire")
        try:
            yield connection
        finally:
            await connection.release()

    container.add_generator(
        borrow_connection,
        provides=Connection,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    return container


async def run_job(
    container: Container,
    started: asyncio.Event,
    finish: asyncio.Event,
) -> None:
    async with container.enter_scope(Scope.REQUEST) as job:
        connection = await job.aresolve(Connection)
        connection.events.append("run")
        started.set()
        # Stand in for work that waits for more input.
        await finish.wait()
        connection.events.append("complete")


async def main() -> None:
    events: list[str] = []
    container = create_container(events)
    started = asyncio.Event()
    task = asyncio.create_task(run_job(container, started, asyncio.Event()))
    try:
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            events.append("cancelled")
    finally:
        await container.aclose()

    print(
        f"lifecycle={','.join(events)}"
    )  # => lifecycle=acquire,run,release:start,release:done,cancelled


if __name__ == "__main__":
    asyncio.run(main())
