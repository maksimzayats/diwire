from __future__ import annotations

from typing import Any

import rodi
from dishka import Provider

from diwire.container import Container as DIWireContainer
from diwire.lock_mode import LockMode
from diwire.providers import Lifetime
from tests.benchmarks.dishka_helpers import DishkaBenchmarkScope, make_dishka_benchmark_container
from tests.benchmarks.helpers import run_benchmark


class _SingletonService:
    pass


def test_benchmark_diwire_resolve_singleton(benchmark: Any) -> None:
    container = DIWireContainer(lock_mode=LockMode.NONE)
    container.add_concrete(_SingletonService, lifetime=Lifetime.SCOPED)
    first = container.resolve(_SingletonService)
    second = container.resolve(_SingletonService)
    assert first is second

    def bench_diwire_singleton() -> None:
        _ = container.resolve(_SingletonService)

    run_benchmark(benchmark, bench_diwire_singleton)


def test_benchmark_rodi_resolve_singleton(benchmark: Any) -> None:
    rodi_container = rodi.Container()
    rodi_container.add_singleton(_SingletonService)
    services = rodi_container.build_provider()
    first = services.get(_SingletonService)
    second = services.get(_SingletonService)
    assert first is second

    def bench_rodi_singleton() -> None:
        _ = services.get(_SingletonService)

    run_benchmark(benchmark, bench_rodi_singleton)


def test_benchmark_dishka_resolve_singleton(benchmark: Any) -> None:
    provider = Provider(scope=DishkaBenchmarkScope.APP)
    provider.provide(_SingletonService, scope=DishkaBenchmarkScope.APP)
    container = make_dishka_benchmark_container(provider)
    first = container.get(_SingletonService)
    second = container.get(_SingletonService)
    assert first is second

    def bench_dishka_singleton() -> None:
        _ = container.get(_SingletonService)

    run_benchmark(benchmark, bench_dishka_singleton)
