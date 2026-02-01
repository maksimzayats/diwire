from __future__ import annotations

from typing import Annotated

from di import Container as DiContainer
from di.dependent import Dependent, Marker
from di.executors import SyncExecutor
from dishka import Provider, Scope, make_container
from pytest_benchmark.fixture import BenchmarkFixture
from rodi import Container as RodiContainer

from diwire import Container, Lifetime
from tests.benchmarks.shared import ScopedGraphRoot, ScopedService, SingletonService

APP_SCOPE = "app"
REQUEST_SCOPE = "request"


def build_di_scoped_graph_root(
    singleton: Annotated[SingletonService, Marker(scope=APP_SCOPE)],
    scoped: Annotated[ScopedService, Marker(scope=REQUEST_SCOPE)],
) -> ScopedGraphRoot:
    return ScopedGraphRoot(singleton=singleton, scoped=scoped)


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


def test_di_request_scoped_resolution(benchmark: BenchmarkFixture) -> None:
    container = DiContainer()
    executor = SyncExecutor()
    dependent = Dependent(build_di_scoped_graph_root, scope=REQUEST_SCOPE)
    solved = container.solve(dependent, scopes=(APP_SCOPE, REQUEST_SCOPE))

    with container.enter_scope(APP_SCOPE) as app_state:
        with app_state.enter_scope(REQUEST_SCOPE) as request_state:
            first = solved.execute_sync(executor, state=request_state)
            second = solved.execute_sync(executor, state=request_state)
            assert first is second

        with app_state.enter_scope(REQUEST_SCOPE) as request_state:
            other = solved.execute_sync(executor, state=request_state)

        assert other is not first

        def resolve_in_scope() -> ScopedGraphRoot:
            with app_state.enter_scope(REQUEST_SCOPE) as request_state:
                return solved.execute_sync(executor, state=request_state)

        result = benchmark(resolve_in_scope)

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
