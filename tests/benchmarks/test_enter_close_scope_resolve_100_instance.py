from __future__ import annotations

from typing import Any

import rodi

from diwire.container import Container as DIWireContainer
from diwire.lock_mode import LockMode

_BENCHMARK_ITERATIONS = 1_000
_BENCHMARK_WARMUP_ROUNDS = 3
_BENCHMARK_ROUNDS = 5


def test_benchmark_diwire_enter_close_scope_resolve_100(benchmark: Any) -> None:
    container = DIWireContainer(lock_mode=LockMode.NONE)
    container.register_instance(int, instance=42)
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
