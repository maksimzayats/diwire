from __future__ import annotations

from typing import Any

import rodi

from diwire.container import Container as DIWireContainer
from diwire.providers import Lifetime
from tests.benchmarks.helpers import run_benchmark


class _TransientService:
    pass


def test_benchmark_diwire_resolve_transient(benchmark: Any) -> None:
    container = DIWireContainer(default_concurrency_safe=False)
    container.register_concrete(_TransientService, lifetime=Lifetime.TRANSIENT)
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
