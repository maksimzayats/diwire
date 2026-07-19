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


def test_benchmark_diwire_resolve_scoped_with_registered_open_closed_generics(
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
        first_int = cast("_ClosedIntRepo", first_scope.resolve(_Repo[int]))
        second_int = cast("_ClosedIntRepo", first_scope.resolve(_Repo[int]))
        first_str = cast("_OpenGenericRepo[str]", first_scope.resolve(_Repo[str]))
        second_str = cast("_OpenGenericRepo[str]", first_scope.resolve(_Repo[str]))
    with container.enter_scope(Scope.REQUEST) as second_scope:
        third_int = cast("_ClosedIntRepo", second_scope.resolve(_Repo[int]))
        third_str = cast("_OpenGenericRepo[str]", second_scope.resolve(_Repo[str]))
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
    with container.enter_scope(Scope.REQUEST) as bench_scope:
        _ = bench_scope.resolve(repo_int)

        def bench_diwire_resolve_scoped_with_registered_open_closed_generics() -> None:
            _ = bench_scope.resolve(repo_int)

        run_benchmark(benchmark, bench_diwire_resolve_scoped_with_registered_open_closed_generics)


def test_benchmark_dishka_resolve_scoped_with_registered_open_closed_generics(
    benchmark: Any,
) -> None:
    provider = Provider(scope=DishkaBenchmarkScope.APP)
    provider.provide(_OpenGenericRepo, provides=_Repo, scope=DishkaBenchmarkScope.REQUEST)
    provider.provide(_ClosedIntRepo, provides=_Repo[int], scope=DishkaBenchmarkScope.REQUEST)
    container = make_dishka_benchmark_container(provider)

    with container(scope=DishkaBenchmarkScope.REQUEST) as first_scope:
        first_int = cast("_ClosedIntRepo", first_scope.get(_Repo[int]))
        second_int = cast("_ClosedIntRepo", first_scope.get(_Repo[int]))
        first_str = cast("_OpenGenericRepo[str]", first_scope.get(_Repo[str]))
        second_str = cast("_OpenGenericRepo[str]", first_scope.get(_Repo[str]))
    with container(scope=DishkaBenchmarkScope.REQUEST) as second_scope:
        third_int = cast("_ClosedIntRepo", second_scope.get(_Repo[int]))
        third_str = cast("_OpenGenericRepo[str]", second_scope.get(_Repo[str]))
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
    with container(scope=DishkaBenchmarkScope.REQUEST) as bench_scope:
        _ = bench_scope.get(repo_int)

        def bench_dishka_resolve_scoped_with_registered_open_closed_generics() -> None:
            _ = bench_scope.get(repo_int)

        run_benchmark(benchmark, bench_dishka_resolve_scoped_with_registered_open_closed_generics)
