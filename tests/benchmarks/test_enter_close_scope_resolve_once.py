from __future__ import annotations

from typing import Any

import rodi
from wireup import injectable

from tests.benchmarks.dishka_helpers import DishkaBenchmarkScope, make_dishka_benchmark_container
from tests.benchmarks.helpers import make_diwire_benchmark_container
from tests.benchmarks.wireup_helpers import make_wireup_benchmark_container

_BENCHMARK_ITERATIONS = 100_000
_BENCHMARK_WARMUP_ROUNDS = 3
_BENCHMARK_ROUNDS = 5


@injectable(lifetime="singleton")
class _SingletonValue:
    def __init__(self) -> None:
        self.value = 42


def test_benchmark_diwire_enter_close_scope_resolve_once(benchmark: Any) -> None:
    container = make_diwire_benchmark_container()
    container.add_instance(42, provides=int)
    container.compile()
    assert container.resolve(int) == 42
    with container.enter_scope() as scope:
        assert scope.resolve(int) == 42

    def bench_diwire_enter_scope() -> None:
        with container.enter_scope() as scope:
            _ = scope.resolve(int)

    benchmark.pedantic(
        target=bench_diwire_enter_scope,
        warmup_rounds=_BENCHMARK_WARMUP_ROUNDS,
        rounds=_BENCHMARK_ROUNDS,
        iterations=_BENCHMARK_ITERATIONS,
    )


def test_benchmark_rodi_enter_close_scope_resolve_once(benchmark: Any) -> None:
    rodi_container = rodi.Container()
    rodi_container.add_singleton_by_factory(lambda: 42, int)
    services = rodi_container.build_provider()
    assert services.get(int) == 42
    with services.create_scope() as scope:
        assert scope.get(int) == 42

    def bench_rodi_enter_scope() -> None:
        with services.create_scope() as scope:
            _ = scope.get(int)

    benchmark.pedantic(
        target=bench_rodi_enter_scope,
        warmup_rounds=_BENCHMARK_WARMUP_ROUNDS,
        rounds=_BENCHMARK_ROUNDS,
        iterations=_BENCHMARK_ITERATIONS,
    )


def test_benchmark_dishka_enter_close_scope_resolve_once(benchmark: Any) -> None:
    container = make_dishka_benchmark_container(context={int: 42})
    assert container.get(int) == 42
    with container(scope=DishkaBenchmarkScope.REQUEST) as scope:
        assert scope.get(int) == 42

    def bench_dishka_enter_scope() -> None:
        with container(scope=DishkaBenchmarkScope.REQUEST) as scope:
            _ = scope.get(int)

    benchmark.pedantic(
        target=bench_dishka_enter_scope,
        warmup_rounds=_BENCHMARK_WARMUP_ROUNDS,
        rounds=_BENCHMARK_ROUNDS,
        iterations=_BENCHMARK_ITERATIONS,
    )


def test_benchmark_wireup_enter_close_scope_resolve_once(benchmark: Any) -> None:
    container = make_wireup_benchmark_container(_SingletonValue)
    assert container.get(_SingletonValue).value == 42
    with container.enter_scope() as scope:
        assert scope.get(_SingletonValue).value == 42

    def bench_wireup_enter_scope() -> None:
        with container.enter_scope() as scope:
            _ = scope.get(_SingletonValue)

    benchmark.pedantic(
        target=bench_wireup_enter_scope,
        warmup_rounds=_BENCHMARK_WARMUP_ROUNDS,
        rounds=_BENCHMARK_ROUNDS,
        iterations=_BENCHMARK_ITERATIONS,
    )
