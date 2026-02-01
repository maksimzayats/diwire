from __future__ import annotations

from dishka import Provider, Scope, make_container
from pytest_benchmark.fixture import BenchmarkFixture
from rodi import Container as RodiContainer

from diwire import Container, Lifetime
from tests.benchmarks.shared import ScopedGraphRoot, ScopedService, SingletonService


def test_diwire_request_scoped_resolution(benchmark: BenchmarkFixture) -> None:
    container = Container(autoregister=False)
    container.register(SingletonService, lifetime=Lifetime.SINGLETON)
    container.register(ScopedService, lifetime=Lifetime.SCOPED, scope="request")
    container.register(ScopedGraphRoot, lifetime=Lifetime.SCOPED, scope="request")
    container.compile()

    with container.enter_scope("request") as scope:
        first = scope.resolve(ScopedGraphRoot)
        second = scope.resolve(ScopedGraphRoot)
        assert first is second

    with container.enter_scope("request") as scope:
        other = scope.resolve(ScopedGraphRoot)

    assert other is not first

    def resolve_in_scope() -> ScopedGraphRoot:
        with container.enter_scope("request") as scope:
            return scope.resolve(ScopedGraphRoot)

    result = benchmark(resolve_in_scope)

    assert isinstance(result, ScopedGraphRoot)


def test_dishka_request_scoped_resolution(benchmark: BenchmarkFixture) -> None:
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(ScopedService)
    provider.provide(ScopedGraphRoot)
    provider.provide(SingletonService, scope=Scope.APP)
    container = make_container(provider)

    def resolve_in_scope() -> ScopedGraphRoot:
        with container() as request_container:
            return request_container.get(ScopedGraphRoot)

    try:
        with container() as request_container:
            first = request_container.get(ScopedGraphRoot)
            second = request_container.get(ScopedGraphRoot)
            assert first is second

        with container() as request_container:
            other = request_container.get(ScopedGraphRoot)

        assert other is not first

        result = benchmark(resolve_in_scope)
    finally:
        container.close()

    assert isinstance(result, ScopedGraphRoot)


def test_rodi_request_scoped_resolution(benchmark: BenchmarkFixture) -> None:
    container = RodiContainer()
    container.add_singleton(SingletonService)
    container.add_scoped(ScopedService)
    container.add_scoped(ScopedGraphRoot)
    provider = container.provider

    with provider.create_scope() as scope:
        first = scope.get(ScopedGraphRoot)
        second = scope.get(ScopedGraphRoot)
        assert first is second

    with provider.create_scope() as scope:
        other = scope.get(ScopedGraphRoot)

    assert other is not first

    def resolve_in_scope() -> ScopedGraphRoot:
        with provider.create_scope() as scope:
            return scope.get(ScopedGraphRoot)

    result = benchmark(resolve_in_scope)

    assert isinstance(result, ScopedGraphRoot)
