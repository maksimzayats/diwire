from __future__ import annotations

from typing import Any

import rodi

from diwire.container import Container as DIWireContainer

_BENCHMARK_ITERATIONS = 1_000
_BENCHMARK_WARMUP_ROUNDS = 3
_BENCHMARK_ROUNDS = 5


def test_benchmark_diwire_open_scope_resolve_100(benchmark: Any) -> None:
    container = DIWireContainer(default_concurrency_safe=False)
    container.register_instance(int, instance=42)
    _ = container.resolve(int)

    def bench_diwire_enter_scope() -> None:
        with container.enter_scope() as scope:
            for _ in range(100):
                _value = scope.resolve(int)

    benchmark.pedantic(
        target=bench_diwire_enter_scope,
        warmup_rounds=_BENCHMARK_WARMUP_ROUNDS,
        rounds=_BENCHMARK_ROUNDS,
        iterations=_BENCHMARK_ITERATIONS,
    )


def test_benchmark_rodi_open_scope_resolve_100(benchmark: Any) -> None:
    rodi_container = rodi.Container()
    rodi_container.add_singleton_by_factory(lambda: 42, int)
    services = rodi_container.build_provider()
    _ = services.get(int)

    def bench_rodi_enter_scope() -> None:
        with services.create_scope() as scope:
            for _ in range(100):
                _value = scope.get(int)

    benchmark.pedantic(
        target=bench_rodi_enter_scope,
        warmup_rounds=_BENCHMARK_WARMUP_ROUNDS,
        rounds=_BENCHMARK_ROUNDS,
        iterations=_BENCHMARK_ITERATIONS,
    )
