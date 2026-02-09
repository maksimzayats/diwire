from __future__ import annotations

from typing import Any

import rodi

from diwire.container import Container as DIWireContainer

_BENCHMARK_ITERATIONS = 100_000
_BENCHMARK_WARMUP_ROUNDS = 3
_BENCHMARK_ROUNDS = 5


def test_benchmark_diwire_enter_close_scope_no_resolve(benchmark: Any) -> None:
    container = DIWireContainer(default_concurrency_safe=False)
    container.register_instance(int, instance=42)
    assert container.resolve(int) == 42
    with container.enter_scope() as scope:
        assert scope.resolve(int) == 42

    def bench_diwire_enter_close_scope_no_resolve() -> None:
        with container.enter_scope():
            pass

    benchmark.pedantic(
        target=bench_diwire_enter_close_scope_no_resolve,
        warmup_rounds=_BENCHMARK_WARMUP_ROUNDS,
        rounds=_BENCHMARK_ROUNDS,
        iterations=_BENCHMARK_ITERATIONS,
    )


def test_benchmark_rodi_enter_close_scope_no_resolve(benchmark: Any) -> None:
    rodi_container = rodi.Container()
    rodi_container.add_singleton_by_factory(lambda: 42, int)
    services = rodi_container.build_provider()
    assert services.get(int) == 42
    with services.create_scope() as scope:
        assert scope.get(int) == 42

    def bench_rodi_enter_close_scope_no_resolve() -> None:
        with services.create_scope():
            pass

    benchmark.pedantic(
        target=bench_rodi_enter_close_scope_no_resolve,
        warmup_rounds=_BENCHMARK_WARMUP_ROUNDS,
        rounds=_BENCHMARK_ROUNDS,
        iterations=_BENCHMARK_ITERATIONS,
    )
