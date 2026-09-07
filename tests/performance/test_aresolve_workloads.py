from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Generator
from typing import Any, Literal

import pytest

from diwire import Lifetime, Scope
from tests.benchmarks.helpers import make_diwire_benchmark_container, run_benchmark

_BATCH_SIZE = 1_000


class _Service:
    pass


class _Consumer:
    def __init__(self, service: _Service) -> None:
        self.service = service


async def _async_service() -> _Service:
    return _Service()


async def _suspending_service() -> _Service:
    await asyncio.sleep(0)
    return _Service()


def _run_async_benchmark(benchmark: Any, batch: Callable[[], Awaitable[None]]) -> None:
    """Measure batches; loop creation and shutdown are outside the timed region."""
    loop = asyncio.new_event_loop()
    benchmark.extra_info["operations_per_batch"] = _BATCH_SIZE
    try:
        # Check the workload before handing it to the benchmark fixture.
        loop.run_until_complete(batch())

        def run_batch() -> None:
            loop.run_until_complete(batch())

        run_benchmark(benchmark, run_batch, iterations=100)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


@pytest.mark.parametrize("provider_kind", ["sync", "async", "suspending"])
@pytest.mark.parametrize("lifetime", [Lifetime.TRANSIENT, Lifetime.SCOPED])
def test_benchmark_diwire_aresolve_provider(
    benchmark: Any,
    *,
    provider_kind: Literal["sync", "async", "suspending"],
    lifetime: Lifetime,
) -> None:
    container = make_diwire_benchmark_container()
    if provider_kind == "sync":
        container.add(_Service, lifetime=lifetime, scope=Scope.APP)
    else:
        factory = _async_service if provider_kind == "async" else _suspending_service
        container.add_factory(factory, provides=_Service, lifetime=lifetime, scope=Scope.APP)
    resolver = container.compile()

    async def check() -> None:
        first = await resolver.aresolve(_Service)
        second = await resolver.aresolve(_Service)
        assert isinstance(first, _Service)
        assert (first is second) is (lifetime is Lifetime.SCOPED)

    asyncio.run(check())

    async def batch() -> None:
        for _ in range(_BATCH_SIZE):
            await resolver.aresolve(_Service)

    try:
        _run_async_benchmark(benchmark, batch)
    finally:
        asyncio.run(resolver.aclose())


def test_benchmark_diwire_aresolve_mixed_graph(benchmark: Any) -> None:
    container = make_diwire_benchmark_container()
    container.add_factory(_async_service, lifetime=Lifetime.TRANSIENT, scope=Scope.APP)
    container.add(_Consumer, lifetime=Lifetime.TRANSIENT, scope=Scope.APP)
    resolver = container.compile()

    async def check() -> None:
        first = await resolver.aresolve(_Consumer)
        second = await resolver.aresolve(_Consumer)
        assert isinstance(first.service, _Service)
        assert first is not second
        assert first.service is not second.service

    asyncio.run(check())

    async def batch() -> None:
        for _ in range(_BATCH_SIZE):
            await resolver.aresolve(_Consumer)

    try:
        _run_async_benchmark(benchmark, batch)
    finally:
        asyncio.run(resolver.aclose())


@pytest.mark.parametrize("with_cleanup", [False, True], ids=["class", "generator"])
def test_benchmark_diwire_aresolve_scope_lifecycle(
    benchmark: Any,
    *,
    with_cleanup: bool,
) -> None:
    container = make_diwire_benchmark_container()
    opened = 0
    closed = 0
    batches = 0

    def resource() -> Generator[_Service, None, None]:
        nonlocal opened, closed
        opened += 1
        try:
            yield _Service()
        finally:
            closed += 1

    if with_cleanup:
        container.add_generator(resource, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    else:
        container.add(_Service, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    resolver = container.compile()

    async def check() -> None:
        async with resolver.enter_scope(Scope.REQUEST) as first_scope:
            first = await first_scope.aresolve(_Service)
            assert first is await first_scope.aresolve(_Service)
        async with resolver.enter_scope(Scope.REQUEST) as second_scope:
            second = await second_scope.aresolve(_Service)
        assert isinstance(first, _Service)
        assert first is not second

    asyncio.run(check())
    assert opened == closed == (2 if with_cleanup else 0)

    async def batch() -> None:
        nonlocal batches
        for _ in range(_BATCH_SIZE):
            async with resolver.enter_scope(Scope.REQUEST) as scope:
                await scope.aresolve(_Service)
        batches += 1

    try:
        _run_async_benchmark(benchmark, batch)
        assert opened == closed == (2 + batches * _BATCH_SIZE if with_cleanup else 0)
    finally:
        asyncio.run(resolver.aclose())
