from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from dishka import Provider

from diwire import Lifetime, Scope
from tests.benchmarks.dishka_helpers import DishkaBenchmarkScope, make_dishka_benchmark_container
from tests.benchmarks.helpers import make_diwire_benchmark_container, run_benchmark

T = TypeVar("T")


class _Repo(Generic[T]):
    pass


@dataclass
class _OpenGenericRepo(_Repo[T]):
    dependency_type: type[T]


class _ClosedIntRepo(_Repo[int]):
    pass


def test_benchmark_diwire_resolve_scoped_with_registered_open_closed_generics_pair_alternating(
    benchmark: Any,
) -> None:
    container = make_diwire_benchmark_container()
    container.add(
        _OpenGenericRepo,
        provides=_Repo,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container.add(
        _ClosedIntRepo,
        provides=_Repo[int],
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container.compile()

    with container.enter_scope(Scope.REQUEST) as first_scope:
        first_int = cast("Any", first_scope.resolve(_Repo[int]))
        second_int = cast("Any", first_scope.resolve(_Repo[int]))
        first_str = cast("Any", first_scope.resolve(_Repo[str]))
        second_str = cast("Any", first_scope.resolve(_Repo[str]))
    with container.enter_scope(Scope.REQUEST) as second_scope:
        third_int = cast("Any", second_scope.resolve(_Repo[int]))
        third_str = cast("Any", second_scope.resolve(_Repo[str]))
    assert isinstance(first_int, _ClosedIntRepo)
    assert isinstance(second_int, _ClosedIntRepo)
    assert isinstance(third_int, _ClosedIntRepo)
    assert isinstance(first_str, _OpenGenericRepo)
    assert isinstance(second_str, _OpenGenericRepo)
    assert isinstance(third_str, _OpenGenericRepo)
    assert first_int is second_int
    assert first_int is not third_int
    assert first_str is second_str
    assert first_str is not third_str
    assert first_str.dependency_type is str
    assert second_str.dependency_type is str
    assert third_str.dependency_type is str

    repo_int = _Repo[int]
    repo_str = _Repo[str]
    with container.enter_scope(Scope.REQUEST) as bench_scope:
        bench_int = bench_scope.resolve(repo_int)
        bench_str = bench_scope.resolve(repo_str)
        assert bench_scope.resolve(repo_int) is bench_int
        assert bench_scope.resolve(repo_str) is bench_str

        def bench_diwire_resolve_scoped_with_registered_open_closed_generics_pair_alternating() -> (
            None
        ):
            _ = bench_scope.resolve(repo_int)
            _ = bench_scope.resolve(repo_str)

        run_benchmark(
            benchmark,
            bench_diwire_resolve_scoped_with_registered_open_closed_generics_pair_alternating,
        )


def test_benchmark_dishka_resolve_scoped_with_registered_open_closed_generics_pair_alternating(
    benchmark: Any,
) -> None:
    provider = Provider(scope=DishkaBenchmarkScope.APP)
    provider.provide(_OpenGenericRepo, provides=_Repo, scope=DishkaBenchmarkScope.REQUEST)
    provider.provide(_ClosedIntRepo, provides=_Repo[int], scope=DishkaBenchmarkScope.REQUEST)
    container = make_dishka_benchmark_container(provider)

    with container(scope=DishkaBenchmarkScope.REQUEST) as first_scope:
        first_int = cast("Any", first_scope.get(_Repo[int]))
        second_int = cast("Any", first_scope.get(_Repo[int]))
        first_str = cast("Any", first_scope.get(_Repo[str]))
        second_str = cast("Any", first_scope.get(_Repo[str]))
    with container(scope=DishkaBenchmarkScope.REQUEST) as second_scope:
        third_int = cast("Any", second_scope.get(_Repo[int]))
        third_str = cast("Any", second_scope.get(_Repo[str]))
    assert isinstance(first_int, _ClosedIntRepo)
    assert isinstance(second_int, _ClosedIntRepo)
    assert isinstance(third_int, _ClosedIntRepo)
    assert isinstance(first_str, _OpenGenericRepo)
    assert isinstance(second_str, _OpenGenericRepo)
    assert isinstance(third_str, _OpenGenericRepo)
    assert first_int is second_int
    assert first_int is not third_int
    assert first_str is second_str
    assert first_str is not third_str
    assert first_str.dependency_type is str
    assert second_str.dependency_type is str
    assert third_str.dependency_type is str

    repo_int = _Repo[int]
    repo_str = _Repo[str]
    with container(scope=DishkaBenchmarkScope.REQUEST) as bench_scope:
        bench_int = bench_scope.get(repo_int)
        bench_str = bench_scope.get(repo_str)
        assert bench_scope.get(repo_int) is bench_int
        assert bench_scope.get(repo_str) is bench_str

        def bench_dishka_resolve_scoped_with_registered_open_closed_generics_pair_alternating() -> (
            None
        ):
            _ = bench_scope.get(repo_int)
            _ = bench_scope.get(repo_str)

        run_benchmark(
            benchmark,
            bench_dishka_resolve_scoped_with_registered_open_closed_generics_pair_alternating,
        )
