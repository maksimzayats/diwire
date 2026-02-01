from __future__ import annotations

from dishka import Provider, Scope, make_container
from punq import Container as PunqContainer
from pytest_benchmark.fixture import BenchmarkFixture
from rodi import Container as RodiContainer

from diwire import Container, Lifetime
from tests.benchmarks.shared import SingletonService


def test_diwire_singleton_resolution(benchmark: BenchmarkFixture) -> None:
    container = Container(autoregister=False)
    container.register(SingletonService, lifetime=Lifetime.SINGLETON)
    container.compile()

    singleton = container.resolve(SingletonService)
    result = benchmark(container.resolve, SingletonService)

    assert result is singleton


def test_dishka_singleton_resolution(benchmark: BenchmarkFixture) -> None:
    provider = Provider(scope=Scope.APP)
    provider.provide(SingletonService)
    container = make_container(provider)

    try:
        singleton = container.get(SingletonService)
        result = benchmark(container.get, SingletonService)
    finally:
        container.close()

    assert result is singleton


def test_punq_singleton_resolution(benchmark: BenchmarkFixture) -> None:
    container = PunqContainer()
    service = SingletonService()
    container.register(SingletonService, instance=service)

    singleton = container.resolve(SingletonService)
    result = benchmark(container.resolve, SingletonService)

    assert result is singleton is service


def test_rodi_singleton_resolution(benchmark: BenchmarkFixture) -> None:
    container = RodiContainer()
    container.add_singleton(SingletonService)

    singleton = container.resolve(SingletonService)
    result = benchmark(container.resolve, SingletonService)

    assert result is singleton
