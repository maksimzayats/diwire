from __future__ import annotations

from typing import Any

import rodi

from tests.benchmarks.dishka_helpers import DishkaBenchmarkScope, make_dishka_benchmark_container
from tests.benchmarks.helpers import make_diwire_benchmark_container

_BENCHMARK_ITERATIONS = 1_000
_BENCHMARK_WARMUP_ROUNDS = 3
_BENCHMARK_ROUNDS = 5


def test_benchmark_diwire_enter_close_scope_resolve_100(benchmark: Any) -> None:
    container = make_diwire_benchmark_container()
    container.add_instance(42, provides=int)
    container.compile()
    assert container.resolve(int) == 42
    with container.enter_scope() as scope:
        values = [scope.resolve(int) for _ in range(3)]
    assert values == [42, 42, 42]

    def bench_diwire_enter_close_scope_resolve_100() -> None:
        with container.enter_scope() as scope:
            for _ in range(100):
                _value = scope.resolve(int)

    benchmark.pedantic(
        target=bench_diwire_enter_close_scope_resolve_100,
        warmup_rounds=_BENCHMARK_WARMUP_ROUNDS,
        rounds=_BENCHMARK_ROUNDS,
        iterations=_BENCHMARK_ITERATIONS,
    )


def test_benchmark_rodi_enter_close_scope_resolve_100(benchmark: Any) -> None:
    rodi_container = rodi.Container()
    rodi_container.add_singleton_by_factory(lambda: 42, int)
    services = rodi_container.build_provider()
    assert services.get(int) == 42
    with services.create_scope() as scope:
        values = [scope.get(int) for _ in range(3)]
    assert values == [42, 42, 42]

    def bench_rodi_enter_close_scope_resolve_100() -> None:
        with services.create_scope() as scope:
            for _ in range(100):
                _value = scope.get(int)

    benchmark.pedantic(
        target=bench_rodi_enter_close_scope_resolve_100,
        warmup_rounds=_BENCHMARK_WARMUP_ROUNDS,
        rounds=_BENCHMARK_ROUNDS,
        iterations=_BENCHMARK_ITERATIONS,
    )


def test_benchmark_dishka_enter_close_scope_resolve_100(benchmark: Any) -> None:
    container = make_dishka_benchmark_container(context={int: 42})
    assert container.get(int) == 42
    with container(scope=DishkaBenchmarkScope.REQUEST) as scope:
        values = [scope.get(int) for _ in range(3)]
    assert values == [42, 42, 42]

    def bench_dishka_enter_close_scope_resolve_100() -> None:
        with container(scope=DishkaBenchmarkScope.REQUEST) as scope:
            for _ in range(100):
                _value = scope.get(int)

    benchmark.pedantic(
        target=bench_dishka_enter_close_scope_resolve_100,
        warmup_rounds=_BENCHMARK_WARMUP_ROUNDS,
        rounds=_BENCHMARK_ROUNDS,
        iterations=_BENCHMARK_ITERATIONS,
    )
