from __future__ import annotations

import asyncio
import importlib
from collections.abc import AsyncGenerator

import pytest

from diwire import Container, Scope

example = importlib.import_module("examples.ex_18_async.03_cancelled_job_cleanup")


@pytest.fixture()
async def job_container() -> AsyncGenerator[tuple[Container, list[str]], None]:
    events: list[str] = []
    container = example.create_container(events)
    try:
        yield container, events
    finally:
        await container.aclose()


async def test_cancelled_job_awaits_release_before_propagating_cancellation(job_container) -> None:
    container, events = job_container
    started = asyncio.Event()
    task = asyncio.create_task(example.run_job(container, started, asyncio.Event()))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        assert events == ["acquire", "run"]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        assert events == ["acquire", "run", "release:start", "release:done"]
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    # Closing the container must not release the job's connection a second time.
    await container.aclose()
    assert events == ["acquire", "run", "release:start", "release:done"]


async def test_successful_job_also_releases_connection(job_container) -> None:
    container, events = job_container
    finish = asyncio.Event()
    finish.set()
    started = asyncio.Event()

    await example.run_job(container, started, finish)

    assert started.is_set()
    assert events == ["acquire", "run", "complete", "release:start", "release:done"]


async def test_failed_job_releases_connection_and_keeps_original_error(job_container) -> None:
    container, events = job_container
    error = LookupError("job failed")

    class FailedInput(asyncio.Event):
        async def wait(self) -> bool:
            raise error

    with pytest.raises(LookupError, match="job failed") as caught:
        await example.run_job(container, asyncio.Event(), FailedInput())

    assert caught.value is error
    assert events == ["acquire", "run", "release:start", "release:done"]


async def test_connection_is_shared_in_one_job_and_fresh_in_next_job(job_container) -> None:
    container, events = job_container
    async with container.enter_scope(Scope.REQUEST) as job:
        first = await job.aresolve(example.Connection)
        assert await job.aresolve(example.Connection) is first
        assert not first.released
        assert events == ["acquire"]
    assert first.released
    assert events == ["acquire", "release:start", "release:done"]

    async with container.enter_scope(Scope.REQUEST) as job:
        second = await job.aresolve(example.Connection)
        assert second is not first
        assert not second.released
    assert second.released
    assert events == [
        "acquire",
        "release:start",
        "release:done",
        "acquire",
        "release:start",
        "release:done",
    ]


async def test_unused_job_scope_does_not_borrow_connection(job_container) -> None:
    container, events = job_container
    async with container.enter_scope(Scope.REQUEST):
        pass
    assert events == []
