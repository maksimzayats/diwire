from __future__ import annotations

from typing import Any

import punq
import rodi
from dishka import Provider
from wireup import injectable

from diwire import Lifetime
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
    container.add(_DepA, lifetime=Lifetime.TRANSIENT)
    container.add(_DepB, lifetime=Lifetime.TRANSIENT)
    container.add(_DepC, lifetime=Lifetime.TRANSIENT)
    container.add(_DepD, lifetime=Lifetime.TRANSIENT)
    container.add(_DepE, lifetime=Lifetime.TRANSIENT)
    container.add(_Root, lifetime=Lifetime.TRANSIENT)
    container.compile()
    first = container.resolve(_Root)
    second = container.resolve(_Root)
    assert first is not second
    assert first.dep_a is not second.dep_a
    assert first.dep_b is not second.dep_b
    assert first.dep_c is not second.dep_c
    assert first.dep_d is not second.dep_d
    assert first.dep_e is not second.dep_e

    def bench_diwire_wide_graph() -> None:
        _ = container.resolve(_Root)

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
    first = services.get(_Root)
    second = services.get(_Root)
    assert first is not second
    assert first.dep_a is not second.dep_a
    assert first.dep_b is not second.dep_b
    assert first.dep_c is not second.dep_c
    assert first.dep_d is not second.dep_d
    assert first.dep_e is not second.dep_e

    def bench_rodi_wide_graph() -> None:
        _ = services.get(_Root)

    run_benchmark(benchmark, bench_rodi_wide_graph, iterations=25_000)


def test_benchmark_dishka_resolve_wide_transient_graph(benchmark: Any) -> None:
    provider = Provider(scope=DishkaBenchmarkScope.APP)
    provider.provide(_DepA, scope=DishkaBenchmarkScope.APP, cache=False)
    provider.provide(_DepB, scope=DishkaBenchmarkScope.APP, cache=False)
    provider.provide(_DepC, scope=DishkaBenchmarkScope.APP, cache=False)
    provider.provide(_DepD, scope=DishkaBenchmarkScope.APP, cache=False)
    provider.provide(_DepE, scope=DishkaBenchmarkScope.APP, cache=False)
    provider.provide(_Root, scope=DishkaBenchmarkScope.APP, cache=False)
    container = make_dishka_benchmark_container(provider)
    first = container.get(_Root)
    second = container.get(_Root)
    assert first is not second
    assert first.dep_a is not second.dep_a
    assert first.dep_b is not second.dep_b
    assert first.dep_c is not second.dep_c
    assert first.dep_d is not second.dep_d
    assert first.dep_e is not second.dep_e

    def bench_dishka_wide_graph() -> None:
        _ = container.get(_Root)

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


def test_benchmark_punq_resolve_wide_transient_graph(benchmark: Any) -> None:
    container = punq.Container()
    container.register(_DepA)
    container.register(_DepB)
    container.register(_DepC)
    container.register(_DepD)
    container.register(_DepE)
    container.register(_Root)
    first = container.resolve(_Root)
    second = container.resolve(_Root)
    assert first is not second
    assert first.dep_a is not second.dep_a
    assert first.dep_b is not second.dep_b
    assert first.dep_c is not second.dep_c
    assert first.dep_d is not second.dep_d
    assert first.dep_e is not second.dep_e

    def bench_punq_wide_graph() -> None:
        _ = container.resolve(_Root)

    run_benchmark(benchmark, bench_punq_wide_graph, iterations=25_000)
