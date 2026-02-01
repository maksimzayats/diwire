from __future__ import annotations

from dishka import Provider, Scope, make_container
from punq import Container as PunqContainer, Scope as PunqScope
from pytest_benchmark.fixture import BenchmarkFixture
from rodi import Container as RodiContainer

from diwire import Container, Lifetime
from tests.benchmarks.shared import (
    WideDep1,
    WideDep2,
    WideDep3,
    WideDep4,
    WideDep5,
    WideDep6,
    WideDep7,
    WideDep8,
    WideDep9,
    WideDep10,
    WideDep11,
    WideDep12,
    WideDep13,
    WideDep14,
    WideDep15,
    WideDep16,
    WideDep17,
    WideDep18,
    WideDep19,
    WideDep20,
    WideGraphRoot,
)

WIDE_DEPENDENCIES = (
    WideDep1,
    WideDep2,
    WideDep3,
    WideDep4,
    WideDep5,
    WideDep6,
    WideDep7,
    WideDep8,
    WideDep9,
    WideDep10,
    WideDep11,
    WideDep12,
    WideDep13,
    WideDep14,
    WideDep15,
    WideDep16,
    WideDep17,
    WideDep18,
    WideDep19,
    WideDep20,
)


def test_diwire_wide_singleton_resolution(benchmark: BenchmarkFixture) -> None:
    container = Container(autoregister=False)
    for dependency in WIDE_DEPENDENCIES:
        container.register(dependency, lifetime=Lifetime.SINGLETON)
    container.register(WideGraphRoot, lifetime=Lifetime.SINGLETON)
    container.compile()

    singleton = container.resolve(WideGraphRoot)
    result = benchmark(container.resolve, WideGraphRoot)

    assert result is singleton


def test_dishka_wide_singleton_resolution(benchmark: BenchmarkFixture) -> None:
    provider = Provider(scope=Scope.APP)
    for dependency in WIDE_DEPENDENCIES:
        provider.provide(dependency)
    provider.provide(WideGraphRoot)
    container = make_container(provider)

    try:
        singleton = container.get(WideGraphRoot)
        result = benchmark(container.get, WideGraphRoot)
    finally:
        container.close()

    assert result is singleton


def test_punq_wide_singleton_resolution(benchmark: BenchmarkFixture) -> None:
    container = PunqContainer()
    for dependency in WIDE_DEPENDENCIES:
        container.register(dependency, scope=PunqScope.singleton)
    container.register(WideGraphRoot, scope=PunqScope.singleton)

    singleton = container.resolve(WideGraphRoot)
    result = benchmark(container.resolve, WideGraphRoot)

    assert result is singleton


def test_rodi_wide_singleton_resolution(benchmark: BenchmarkFixture) -> None:
    container = RodiContainer()
    for dependency in WIDE_DEPENDENCIES:
        container.add_singleton(dependency)
    container.add_singleton(WideGraphRoot)

    singleton = container.resolve(WideGraphRoot)
    result = benchmark(container.resolve, WideGraphRoot)

    assert result is singleton
