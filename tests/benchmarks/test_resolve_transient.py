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
class _TransientService:
    pass


def test_benchmark_diwire_resolve_transient(benchmark: Any) -> None:
    container = make_diwire_benchmark_container()
    container.add(_TransientService, lifetime=Lifetime.TRANSIENT)
    container.compile()
    first = container.resolve(_TransientService)
    second = container.resolve(_TransientService)
    assert first is not second

    def bench_diwire_transient() -> None:
        _ = container.resolve(_TransientService)

    run_benchmark(benchmark, bench_diwire_transient)


def test_benchmark_rodi_resolve_transient(benchmark: Any) -> None:
    rodi_container = rodi.Container()
    rodi_container.add_transient(_TransientService)
    services = rodi_container.build_provider()
    first = services.get(_TransientService)
    second = services.get(_TransientService)
    assert first is not second

    def bench_rodi_transient() -> None:
        _ = services.get(_TransientService)

    run_benchmark(benchmark, bench_rodi_transient)


def test_benchmark_dishka_resolve_transient(benchmark: Any) -> None:
    provider = Provider(scope=DishkaBenchmarkScope.APP)
    provider.provide(_TransientService, scope=DishkaBenchmarkScope.APP, cache=False)
    container = make_dishka_benchmark_container(provider)
    first = container.get(_TransientService)
    second = container.get(_TransientService)
    assert first is not second

    def bench_dishka_transient() -> None:
        _ = container.get(_TransientService)

    run_benchmark(benchmark, bench_dishka_transient)


def test_benchmark_wireup_resolve_transient(benchmark: Any) -> None:
    container = make_wireup_benchmark_container(_TransientService)
    with container.enter_scope() as scope:
        first = scope.get(_TransientService)
        second = scope.get(_TransientService)
        assert first is not second

        def bench_wireup_transient() -> None:
            _ = scope.get(_TransientService)

        run_benchmark(benchmark, bench_wireup_transient)


def test_benchmark_punq_resolve_transient(benchmark: Any) -> None:
    container = punq.Container()
    container.register(_TransientService)
    first = container.resolve(_TransientService)
    second = container.resolve(_TransientService)
    assert first is not second

    def bench_punq_transient() -> None:
        _ = container.resolve(_TransientService)

    run_benchmark(benchmark, bench_punq_transient)
