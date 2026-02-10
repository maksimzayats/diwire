from __future__ import annotations

from typing import Any

import rodi

from diwire.container import Container as DIWireContainer
from diwire.lock_mode import LockMode
from diwire.providers import Lifetime
from tests.benchmarks.helpers import run_benchmark


class _Dep0:
    pass


class _Dep1:
    def __init__(self, dep_0: _Dep0) -> None:
        self.dep_0 = dep_0


class _Dep2:
    def __init__(self, dep_1: _Dep1) -> None:
        self.dep_1 = dep_1


class _Dep3:
    def __init__(self, dep_2: _Dep2) -> None:
        self.dep_2 = dep_2


class _Dep4:
    def __init__(self, dep_3: _Dep3) -> None:
        self.dep_3 = dep_3


class _Root:
    def __init__(self, dep_4: _Dep4) -> None:
        self.dep_4 = dep_4


def test_benchmark_diwire_resolve_deep_transient_chain(benchmark: Any) -> None:
    container = DIWireContainer(lock_mode=LockMode.NONE)
    container.register_concrete(_Dep0, lifetime=Lifetime.TRANSIENT)
    container.register_concrete(_Dep1, lifetime=Lifetime.TRANSIENT)
    container.register_concrete(_Dep2, lifetime=Lifetime.TRANSIENT)
    container.register_concrete(_Dep3, lifetime=Lifetime.TRANSIENT)
    container.register_concrete(_Dep4, lifetime=Lifetime.TRANSIENT)
    container.register_concrete(_Root, lifetime=Lifetime.TRANSIENT)
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
