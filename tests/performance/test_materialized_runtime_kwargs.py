from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

import pytest

from diwire import Container, Lifetime
from tests.benchmarks.helpers import make_diwire_benchmark_container, run_benchmark

T = TypeVar("T")


class Shared:
    pass


@dataclass
class Repo(Generic[T]):
    shared: Shared
    type_arg: type[T]


def _create_repo(shared: Shared, type_arg: type[T]) -> Repo[T]:
    return Repo(shared, type_arg)


def _create_keyword_repo(shared: Shared, *, type_arg: type[T]) -> Repo[T]:
    return Repo(shared, type_arg)


def make_runtime_kwargs_workload(factory: Any) -> tuple[Container, Shared]:
    container = make_diwire_benchmark_container()
    shared = Shared()
    container.add_instance(shared)
    container.add_factory(factory, provides=Repo, lifetime=Lifetime.TRANSIENT)
    container.compile()
    return container, shared


@pytest.mark.parametrize("factory", [_create_repo, _create_keyword_repo])
def test_benchmark_diwire_materialized_runtime_kwargs(benchmark: Any, factory: Any) -> None:
    container, shared = make_runtime_kwargs_workload(factory)
    key = Repo[int]
    first = container.resolve(key)
    second = container.resolve(key)
    other = container.resolve(Repo[str])
    assert first is not second
    assert first.shared is second.shared is other.shared is shared
    assert first.type_arg is second.type_arg is int
    assert other.type_arg is str
    materialized = container._providers_registrations.get_by_type(key)
    wrapper = materialized.factory
    assert wrapper is not None
    assert cast("Any", wrapper).__code__.co_name == "_wrapper"

    def resolve() -> None:
        container.resolve(key)

    benchmark.extra_info["operation"] = "public transient resolve; materialization excluded"
    try:
        run_benchmark(benchmark, resolve)
    finally:
        container.close()
