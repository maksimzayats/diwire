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
class _Dep0:
    pass


@injectable(lifetime="transient")
class _Dep1:
    def __init__(self, dep_0: _Dep0) -> None:
        self.dep_0 = dep_0


@injectable(lifetime="transient")
class _Dep2:
    def __init__(self, dep_1: _Dep1) -> None:
        self.dep_1 = dep_1


@injectable(lifetime="transient")
class _Dep3:
    def __init__(self, dep_2: _Dep2) -> None:
        self.dep_2 = dep_2


@injectable(lifetime="transient")
class _Dep4:
    def __init__(self, dep_3: _Dep3) -> None:
        self.dep_3 = dep_3


@injectable(lifetime="transient")
class _Root:
    def __init__(self, dep_4: _Dep4) -> None:
        self.dep_4 = dep_4


def test_benchmark_diwire_resolve_deep_transient_chain(benchmark: Any) -> None:
    container = make_diwire_benchmark_container()
    container.add(_Dep0, lifetime=Lifetime.TRANSIENT)
    container.add(_Dep1, lifetime=Lifetime.TRANSIENT)
    container.add(_Dep2, lifetime=Lifetime.TRANSIENT)
    container.add(_Dep3, lifetime=Lifetime.TRANSIENT)
    container.add(_Dep4, lifetime=Lifetime.TRANSIENT)
    container.add(_Root, lifetime=Lifetime.TRANSIENT)
    container.compile()
    first = container.resolve(_Root)
    second = container.resolve(_Root)
    assert first is not second
    assert first.dep_4 is not second.dep_4
    assert first.dep_4.dep_3.dep_2.dep_1.dep_0 is not second.dep_4.dep_3.dep_2.dep_1.dep_0

    def bench_diwire_deep_chain() -> None:
        _ = container.resolve(_Root)

    run_benchmark(benchmark, bench_diwire_deep_chain, iterations=25_000)


def test_benchmark_rodi_resolve_deep_transient_chain(benchmark: Any) -> None:
    rodi_container = rodi.Container()
    rodi_container.add_transient(_Dep0)
    rodi_container.add_transient(_Dep1)
    rodi_container.add_transient(_Dep2)
    rodi_container.add_transient(_Dep3)
    rodi_container.add_transient(_Dep4)
    rodi_container.add_transient(_Root)
    services = rodi_container.build_provider()
    first = services.get(_Root)
    second = services.get(_Root)
    assert first is not second
    assert first.dep_4 is not second.dep_4
    assert first.dep_4.dep_3.dep_2.dep_1.dep_0 is not second.dep_4.dep_3.dep_2.dep_1.dep_0

    def bench_rodi_deep_chain() -> None:
        _ = services.get(_Root)

    run_benchmark(benchmark, bench_rodi_deep_chain, iterations=25_000)


def test_benchmark_dishka_resolve_deep_transient_chain(benchmark: Any) -> None:
    provider = Provider(scope=DishkaBenchmarkScope.APP)
    provider.provide(_Dep0, scope=DishkaBenchmarkScope.APP, cache=False)
    provider.provide(_Dep1, scope=DishkaBenchmarkScope.APP, cache=False)
    provider.provide(_Dep2, scope=DishkaBenchmarkScope.APP, cache=False)
    provider.provide(_Dep3, scope=DishkaBenchmarkScope.APP, cache=False)
    provider.provide(_Dep4, scope=DishkaBenchmarkScope.APP, cache=False)
    provider.provide(_Root, scope=DishkaBenchmarkScope.APP, cache=False)
    container = make_dishka_benchmark_container(provider)
    first = container.get(_Root)
    second = container.get(_Root)
    assert first is not second
    assert first.dep_4 is not second.dep_4
    assert first.dep_4.dep_3.dep_2.dep_1.dep_0 is not second.dep_4.dep_3.dep_2.dep_1.dep_0

    def bench_dishka_deep_chain() -> None:
        _ = container.get(_Root)

    run_benchmark(benchmark, bench_dishka_deep_chain, iterations=25_000)


def test_benchmark_wireup_resolve_deep_transient_chain(benchmark: Any) -> None:
    container = make_wireup_benchmark_container(_Dep0, _Dep1, _Dep2, _Dep3, _Dep4, _Root)
    with container.enter_scope() as scope:
        first = scope.get(_Root)
        second = scope.get(_Root)
        assert first is not second
        assert first.dep_4 is not second.dep_4
        assert first.dep_4.dep_3.dep_2.dep_1.dep_0 is not second.dep_4.dep_3.dep_2.dep_1.dep_0

        def bench_wireup_deep_chain() -> None:
            _ = scope.get(_Root)

        run_benchmark(benchmark, bench_wireup_deep_chain, iterations=25_000)


def test_benchmark_punq_resolve_deep_transient_chain(benchmark: Any) -> None:
    container = punq.Container()
    container.register(_Dep0)
    container.register(_Dep1)
    container.register(_Dep2)
    container.register(_Dep3)
    container.register(_Dep4)
    container.register(_Root)
    first = container.resolve(_Root)
    second = container.resolve(_Root)
    assert first is not second
    assert first.dep_4 is not second.dep_4
    assert first.dep_4.dep_3.dep_2.dep_1.dep_0 is not second.dep_4.dep_3.dep_2.dep_1.dep_0

    def bench_punq_deep_chain() -> None:
        _ = container.resolve(_Root)

    run_benchmark(benchmark, bench_punq_deep_chain, iterations=25_000)
