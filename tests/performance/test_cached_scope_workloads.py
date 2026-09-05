from __future__ import annotations

import asyncio
from typing import Any, Literal

import pytest

from diwire import Lifetime, LockMode, Scope
from tests.benchmarks.helpers import make_diwire_benchmark_container, run_benchmark
from tests.performance.test_aresolve_workloads import _BATCH_SIZE, _run_async_benchmark


class _ScopedService:
    pass


@pytest.mark.parametrize("provider_kind", ["sync", "async", "suspending"])
def test_benchmark_diwire_aresolve_warm_request_cache(
    benchmark: Any,
    provider_kind: Literal["sync", "async", "suspending"],
) -> None:
    calls = 0

    def sync_factory() -> _ScopedService:
        nonlocal calls
        calls += 1
        return _ScopedService()

    async def async_factory() -> _ScopedService:
        nonlocal calls
        calls += 1
        if provider_kind == "suspending":
            await asyncio.sleep(0)
        return _ScopedService()

    container = make_diwire_benchmark_container()
    factory = sync_factory if provider_kind == "sync" else async_factory
    container.add_factory(
        factory, provides=_ScopedService, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST
    )
    resolver = container.compile()
    try:
        with resolver.enter_scope(Scope.REQUEST) as scope:
            first = asyncio.run(scope.aresolve(_ScopedService))
            assert first is asyncio.run(scope.aresolve(_ScopedService))
            assert calls == 1

            async def batch() -> None:
                for _ in range(_BATCH_SIZE):
                    await scope.aresolve(_ScopedService)

            _run_async_benchmark(benchmark, batch)
            assert calls == 1
            assert first is asyncio.run(scope.aresolve(_ScopedService))

        with resolver.enter_scope(Scope.REQUEST) as next_scope:
            assert first is not asyncio.run(next_scope.aresolve(_ScopedService))
        assert calls == 2
    finally:
        asyncio.run(resolver.aclose())


def test_benchmark_diwire_resolve_warm_request_cache_with_thread_lock(benchmark: Any) -> None:
    calls = 0

    def factory() -> _ScopedService:
        nonlocal calls
        calls += 1
        return _ScopedService()

    container = make_diwire_benchmark_container()
    container.add_factory(
        factory,
        provides=_ScopedService,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
        lock_mode=LockMode.THREAD,
    )
    resolver = container.compile()
    try:
        with resolver.enter_scope(Scope.REQUEST) as scope:
            first = scope.resolve(_ScopedService)
            assert first is scope.resolve(_ScopedService)
            assert calls == 1

            def resolve() -> None:
                scope.resolve(_ScopedService)

            run_benchmark(benchmark, resolve)
            assert calls == 1
            assert first is scope.resolve(_ScopedService)

        with resolver.enter_scope(Scope.REQUEST) as next_scope:
            assert first is not next_scope.resolve(_ScopedService)
        assert calls == 2
    finally:
        resolver.close()
