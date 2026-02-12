from __future__ import annotations

from typing import Any

import rodi
from dishka import Provider

from diwire.providers import Lifetime
from diwire.scope import Scope
from tests.benchmarks.dishka_helpers import DishkaBenchmarkScope, make_dishka_benchmark_container
from tests.benchmarks.helpers import make_diwire_benchmark_container, run_benchmark


class _SharedDependency:
    pass


class _PerResolveDependency:
    def __init__(self, shared: _SharedDependency) -> None:
        self.shared = shared


class _RootScopedService:
    def __init__(self, dependency: _PerResolveDependency) -> None:
        self.dependency = dependency


def test_benchmark_diwire_resolve_mixed_lifetimes(benchmark: Any) -> None:
    container = make_diwire_benchmark_container()
    container.add_concrete(_SharedDependency, lifetime=Lifetime.SCOPED)
    container.add_concrete(_PerResolveDependency, lifetime=Lifetime.TRANSIENT)
    container.add_concrete(
        _RootScopedService,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container.compile()
    with container.enter_scope(Scope.REQUEST) as first_scope:
        first = first_scope.resolve(_RootScopedService)
        second = first_scope.resolve(_RootScopedService)
    with container.enter_scope(Scope.REQUEST) as second_scope:
        third = second_scope.resolve(_RootScopedService)
    assert first is second
    assert first is not third
    assert first.dependency is second.dependency
    assert first.dependency is not third.dependency
    assert first.dependency.shared is third.dependency.shared

    def bench_diwire_mixed_lifetimes() -> None:
        with container.enter_scope(Scope.REQUEST) as scope:
            _ = scope.resolve(_RootScopedService)

    run_benchmark(benchmark, bench_diwire_mixed_lifetimes)


def test_benchmark_rodi_resolve_mixed_lifetimes(benchmark: Any) -> None:
    rodi_container = rodi.Container()
    rodi_container.add_singleton(_SharedDependency)
    rodi_container.add_transient(_PerResolveDependency)
    rodi_container.add_scoped(_RootScopedService)
    services = rodi_container.build_provider()
    with services.create_scope() as first_scope:
        first = first_scope.get(_RootScopedService)
        second = first_scope.get(_RootScopedService)
    with services.create_scope() as second_scope:
        third = second_scope.get(_RootScopedService)
    assert first is second
    assert first is not third
    assert first.dependency is second.dependency
    assert first.dependency is not third.dependency
    assert first.dependency.shared is third.dependency.shared

    def bench_rodi_mixed_lifetimes() -> None:
        with services.create_scope() as scope:
            _ = scope.get(_RootScopedService)

    run_benchmark(benchmark, bench_rodi_mixed_lifetimes)


def test_benchmark_dishka_resolve_mixed_lifetimes(benchmark: Any) -> None:
    provider = Provider(scope=DishkaBenchmarkScope.APP)
    provider.provide(_SharedDependency, scope=DishkaBenchmarkScope.APP)
    provider.provide(_PerResolveDependency, scope=DishkaBenchmarkScope.REQUEST, cache=False)
    provider.provide(_RootScopedService, scope=DishkaBenchmarkScope.REQUEST)
    container = make_dishka_benchmark_container(provider)
    with container(scope=DishkaBenchmarkScope.REQUEST) as first_scope:
        first = first_scope.get(_RootScopedService)
        second = first_scope.get(_RootScopedService)
    with container(scope=DishkaBenchmarkScope.REQUEST) as second_scope:
        third = second_scope.get(_RootScopedService)
    assert first is second
    assert first is not third
    assert first.dependency is second.dependency
    assert first.dependency is not third.dependency
    assert first.dependency.shared is third.dependency.shared

    def bench_dishka_mixed_lifetimes() -> None:
        with container(scope=DishkaBenchmarkScope.REQUEST) as scope:
            _ = scope.get(_RootScopedService)

    run_benchmark(benchmark, bench_dishka_mixed_lifetimes)
