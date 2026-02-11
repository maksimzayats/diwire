from __future__ import annotations

from typing import Any

import rodi
from dishka import Provider

from diwire.container import Container as DIWireContainer
from diwire.lock_mode import LockMode
from diwire.providers import Lifetime
from diwire.scope import Scope
from tests.benchmarks.dishka_helpers import DishkaBenchmarkScope, make_dishka_benchmark_container
from tests.benchmarks.helpers import run_benchmark


class _ScopedService:
    pass


def test_benchmark_diwire_enter_close_scope_resolve_scoped_100(benchmark: Any) -> None:
    container = DIWireContainer(lock_mode=LockMode.NONE)
    container.add_concrete(
        _ScopedService,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    with container.enter_scope(Scope.REQUEST) as first_scope:
        first = first_scope.resolve(_ScopedService)
        second = first_scope.resolve(_ScopedService)
    with container.enter_scope(Scope.REQUEST) as second_scope:
        third = second_scope.resolve(_ScopedService)
    assert first is second
    assert first is not third

    def bench_diwire_enter_close_scope_resolve_scoped_100() -> None:
        with container.enter_scope(Scope.REQUEST) as scope:
            for _ in range(100):
                _ = scope.resolve(_ScopedService)

    run_benchmark(benchmark, bench_diwire_enter_close_scope_resolve_scoped_100, iterations=1_000)


def test_benchmark_rodi_enter_close_scope_resolve_scoped_100(benchmark: Any) -> None:
    rodi_container = rodi.Container()
    rodi_container.add_scoped(_ScopedService)
    services = rodi_container.build_provider()
    with services.create_scope() as first_scope:
        first = first_scope.get(_ScopedService)
        second = first_scope.get(_ScopedService)
    with services.create_scope() as second_scope:
        third = second_scope.get(_ScopedService)
    assert first is second
    assert first is not third

    def bench_rodi_enter_close_scope_resolve_scoped_100() -> None:
        with services.create_scope() as scope:
            for _ in range(100):
                _ = scope.get(_ScopedService)

    run_benchmark(benchmark, bench_rodi_enter_close_scope_resolve_scoped_100, iterations=1_000)


def test_benchmark_dishka_enter_close_scope_resolve_scoped_100(benchmark: Any) -> None:
    provider = Provider(scope=DishkaBenchmarkScope.APP)
    provider.provide(_ScopedService, scope=DishkaBenchmarkScope.REQUEST)
    container = make_dishka_benchmark_container(provider)
    with container(scope=DishkaBenchmarkScope.REQUEST) as first_scope:
        first = first_scope.get(_ScopedService)
        second = first_scope.get(_ScopedService)
    with container(scope=DishkaBenchmarkScope.REQUEST) as second_scope:
        third = second_scope.get(_ScopedService)
    assert first is second
    assert first is not third

    def bench_dishka_enter_close_scope_resolve_scoped_100() -> None:
        with container(scope=DishkaBenchmarkScope.REQUEST) as scope:
            for _ in range(100):
                _ = scope.get(_ScopedService)

    run_benchmark(benchmark, bench_dishka_enter_close_scope_resolve_scoped_100, iterations=1_000)
