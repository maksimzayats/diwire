from __future__ import annotations

import gc
from typing import Any

import pytest

from diwire import Container, Lifetime, Scope
from tests.benchmarks.helpers import make_diwire_benchmark_container


def make_compile_workload(provider_count: int) -> tuple[Container, tuple[type[object], ...]]:
    """Prepare registrations without compiling or resolving the graph."""
    services = tuple(type(f"Service{index}", (), {}) for index in range(provider_count))
    container = make_diwire_benchmark_container()
    for service in services:
        container.add(service, lifetime=Lifetime.TRANSIENT, scope=Scope.REQUEST)
    return container, services


@pytest.mark.parametrize("provider_count", [16, 64, 256])
def test_benchmark_diwire_cold_compile(benchmark: Any, provider_count: int) -> None:
    current: Container | None = None
    services: tuple[type[object], ...] = ()

    def setup() -> tuple[tuple[Container], dict[str, object]]:
        nonlocal current, services
        current = None
        gc.collect()
        current, services = make_compile_workload(provider_count)
        assert current._root_resolver is None
        return (current,), {}

    def compile_container(container: Container) -> None:
        container.compile()

    def teardown(container: Container) -> None:
        nonlocal current
        assert container._root_resolver is not None
        with container.enter_scope(Scope.REQUEST) as scope:
            for service in (services[0], services[-1]):
                first = scope.resolve(service)
                assert isinstance(first, service)
                assert first is not scope.resolve(service)
        container.close()
        current = None

    benchmark.extra_info["provider_count"] = provider_count
    benchmark.extra_info["operation"] = "cold compile; registrations and teardown excluded"
    benchmark.extra_info["gc_policy"] = "enabled during compile; collect before setup"
    try:
        benchmark.pedantic(
            compile_container,
            setup=setup,
            teardown=teardown,
            iterations=1,
            rounds=20,
            warmup_rounds=3,
        )
    finally:
        # pytest-benchmark omits teardown in --benchmark-disable mode.
        if current is not None:
            teardown(current)
