from __future__ import annotations

from typing import Any

import rodi
from dishka import Provider
from wireup import injectable

from diwire import Lifetime, Scope
from tests.benchmarks.dishka_helpers import DishkaBenchmarkScope, make_dishka_benchmark_container
from tests.benchmarks.helpers import make_diwire_benchmark_container, run_benchmark
from tests.benchmarks.wireup_helpers import make_wireup_benchmark_container


@injectable(lifetime="transient")
class _DepA:
    pass


@injectable(lifetime="transient")
class _DepB:
    pass


@injectable(lifetime="transient")
class _DepC:
    pass


@injectable(lifetime="transient")
class _DepD:
    pass


@injectable(lifetime="transient")
class _DepE:
    pass


@injectable(lifetime="transient")
class _Root:
    def __init__(
        self,
        dep_a: _DepA,
        dep_b: _DepB,
        dep_c: _DepC,
        dep_d: _DepD,
        dep_e: _DepE,
    ) -> None:
        self.dep_a = dep_a
        self.dep_b = dep_b
        self.dep_c = dep_c
        self.dep_d = dep_d
        self.dep_e = dep_e


def test_benchmark_diwire_resolve_wide_transient_graph(benchmark: Any) -> None:
    container = make_diwire_benchmark_container()
    container.add(_DepA, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    container.add(_DepB, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    container.add(_DepC, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    container.add(_DepD, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    container.add(_DepE, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    container.add(_Root, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    container.compile()
    with container.enter_scope(Scope.REQUEST) as scope:
        first = scope.resolve(_Root)
        second = scope.resolve(_Root)
        assert first is not second
        assert first.dep_a is not second.dep_a
        assert first.dep_b is not second.dep_b
        assert first.dep_c is not second.dep_c
        assert first.dep_d is not second.dep_d
        assert first.dep_e is not second.dep_e

        def bench_diwire_wide_graph() -> None:
            _ = scope.resolve(_Root)

        run_benchmark(benchmark, bench_diwire_wide_graph, iterations=25_000)


def test_benchmark_rodi_resolve_wide_transient_graph(benchmark: Any) -> None:
    rodi_container = rodi.Container()
    rodi_container.add_transient(_DepA)
    rodi_container.add_transient(_DepB)
    rodi_container.add_transient(_DepC)
    rodi_container.add_transient(_DepD)
    rodi_container.add_transient(_DepE)
    rodi_container.add_transient(_Root)
    services = rodi_container.build_provider()
    with services.create_scope() as scope:
        first = scope.get(_Root)
        second = scope.get(_Root)
        assert first is not second
        assert first.dep_a is not second.dep_a
        assert first.dep_b is not second.dep_b
        assert first.dep_c is not second.dep_c
        assert first.dep_d is not second.dep_d
        assert first.dep_e is not second.dep_e

        def bench_rodi_wide_graph() -> None:
            _ = scope.get(_Root)

        run_benchmark(benchmark, bench_rodi_wide_graph, iterations=25_000)


def test_benchmark_dishka_resolve_wide_transient_graph(benchmark: Any) -> None:
    provider = Provider(scope=DishkaBenchmarkScope.APP)
    provider.provide(_DepA, scope=DishkaBenchmarkScope.REQUEST, cache=False)
    provider.provide(_DepB, scope=DishkaBenchmarkScope.REQUEST, cache=False)
    provider.provide(_DepC, scope=DishkaBenchmarkScope.REQUEST, cache=False)
    provider.provide(_DepD, scope=DishkaBenchmarkScope.REQUEST, cache=False)
    provider.provide(_DepE, scope=DishkaBenchmarkScope.REQUEST, cache=False)
    provider.provide(_Root, scope=DishkaBenchmarkScope.REQUEST, cache=False)
    container = make_dishka_benchmark_container(provider)
    with container(scope=DishkaBenchmarkScope.REQUEST) as scope:
        first = scope.get(_Root)
        second = scope.get(_Root)
        assert first is not second
        assert first.dep_a is not second.dep_a
        assert first.dep_b is not second.dep_b
        assert first.dep_c is not second.dep_c
        assert first.dep_d is not second.dep_d
        assert first.dep_e is not second.dep_e

        def bench_dishka_wide_graph() -> None:
            _ = scope.get(_Root)

        run_benchmark(benchmark, bench_dishka_wide_graph, iterations=25_000)


def test_benchmark_wireup_resolve_wide_transient_graph(benchmark: Any) -> None:
    container = make_wireup_benchmark_container(_DepA, _DepB, _DepC, _DepD, _DepE, _Root)
    with container.enter_scope() as scope:
        first = scope.get(_Root)
        second = scope.get(_Root)
        assert first is not second
        assert first.dep_a is not second.dep_a
        assert first.dep_b is not second.dep_b
        assert first.dep_c is not second.dep_c
        assert first.dep_d is not second.dep_d
        assert first.dep_e is not second.dep_e

        def bench_wireup_wide_graph() -> None:
            _ = scope.get(_Root)

        run_benchmark(benchmark, bench_wireup_wide_graph, iterations=25_000)
