from __future__ import annotations

from typing import Any

import rodi

from diwire.container import Container as DIWireContainer
from diwire.providers import Lifetime
from diwire.scope import Scope
from tests.benchmarks.helpers import run_benchmark


class _ScopedService:
    pass


def test_benchmark_diwire_resolve_scoped(benchmark: Any) -> None:
    container = DIWireContainer(default_concurrency_safe=False)
    container.register_concrete(
        _ScopedService,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    with container.enter_scope(Scope.REQUEST) as first_scope:
        first = first_scope.resolve(_ScopedService)
        second = first_scope.resolve(_ScopedService)
    with container.enter_scope(Scope.REQUEST) as second_scope:
        third = second_scope.resolve(_ScopedService)
    assert first is second
    assert first is not third

    def bench_diwire_scoped() -> None:
        with container.enter_scope(Scope.REQUEST) as scope:
            _ = scope.resolve(_ScopedService)

    run_benchmark(benchmark, bench_diwire_scoped)


def test_benchmark_rodi_resolve_scoped(benchmark: Any) -> None:
    rodi_container = rodi.Container()
    rodi_container.add_scoped(_ScopedService)
    services = rodi_container.build_provider()
    with services.create_scope() as first_scope:
        first = first_scope.get(_ScopedService)
        second = first_scope.get(_ScopedService)
    with services.create_scope() as second_scope:
        third = second_scope.get(_ScopedService)
    assert first is second
    assert first is not third

    def bench_rodi_scoped() -> None:
        with services.create_scope() as scope:
            _ = scope.get(_ScopedService)

    run_benchmark(benchmark, bench_rodi_scoped)
