from __future__ import annotations

from typing import Any

import rodi
from wireup import instance

from tests.benchmarks.dishka_helpers import DishkaBenchmarkScope, make_dishka_benchmark_container
from tests.benchmarks.helpers import make_diwire_benchmark_container
from tests.benchmarks.wireup_helpers import make_wireup_benchmark_container

_BENCHMARK_ITERATIONS = 1_000
_BENCHMARK_WARMUP_ROUNDS = 3
_BENCHMARK_ROUNDS = 5


def test_benchmark_diwire_enter_close_scope_resolve_100(benchmark: Any) -> None:
    value = int("1000")
    container = make_diwire_benchmark_container()
    container.add_instance(value, provides=int)
    container.compile()
    assert container.resolve(int) is value
    with container.enter_scope() as scope:
        values = [scope.resolve(int) for _ in range(3)]
    assert all(item is value for item in values)

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
    value = int("1000")
    rodi_container = rodi.Container()
    rodi_container.add_instance(value, declared_class=int)
    services = rodi_container.build_provider()
    assert services.get(int) is value
    with services.create_scope() as scope:
        values = [scope.get(int) for _ in range(3)]
    assert all(item is value for item in values)

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
    value = int("1000")
    container = make_dishka_benchmark_container(context={int: value})
    assert container.get(int) is value
    with container(scope=DishkaBenchmarkScope.REQUEST) as scope:
        values = [scope.get(int) for _ in range(3)]
    assert all(item is value for item in values)

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


def test_benchmark_wireup_enter_close_scope_resolve_100(benchmark: Any) -> None:
    value = int("1000")
    container = make_wireup_benchmark_container(instance(value, as_type=int))
    assert container.get(int) is value
    with container.enter_scope() as scope:
        values = [scope.get(int) for _ in range(3)]
    assert all(item is value for item in values)

    def bench_wireup_enter_close_scope_resolve_100() -> None:
        with container.enter_scope() as scope:
            for _ in range(100):
                _value = scope.get(int)

    benchmark.pedantic(
        target=bench_wireup_enter_close_scope_resolve_100,
        warmup_rounds=_BENCHMARK_WARMUP_ROUNDS,
        rounds=_BENCHMARK_ROUNDS,
        iterations=_BENCHMARK_ITERATIONS,
    )
