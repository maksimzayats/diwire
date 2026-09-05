from __future__ import annotations

import gc
from dataclasses import dataclass, make_dataclass
from typing import Any, Generic, TypeVar, cast

import pytest

from diwire import Container, DependencyRegistrationPolicy, Lifetime, LockMode, MissingPolicy, Scope

_T = TypeVar("_T")


class _Repo(Generic[_T]):
    pass


@dataclass
class _GenericRepo(_Repo[_T]):
    entity_type: type[_T]


@pytest.mark.parametrize("provider_count", [64, 256])
def test_benchmark_diwire_generic_cold_compile(benchmark: Any, provider_count: int) -> None:
    entities: tuple[type[object], ...] = tuple(
        type(f"Entity{index}", (), {}) for index in range(provider_count)
    )
    # Runtime-created classes cannot be expressed as static type parameters.
    generic_key = cast("Any", _Repo)
    keys: tuple[object, ...] = tuple(generic_key[entity] for entity in entities)
    consumers: tuple[type[object], ...] = tuple(
        make_dataclass(f"Consumer{index}", [("repo", key)]) for index, key in enumerate(keys)
    )
    current: Container | None = None

    def setup() -> tuple[tuple[Container], dict[str, object]]:
        nonlocal current
        current = Container(
            missing_policy=MissingPolicy.ERROR,
            dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
            lock_mode=LockMode.NONE,
            use_resolver_context=False,
        )
        current.add(_GenericRepo, provides=_Repo, lifetime=Lifetime.SCOPED, scope=Scope.APP)
        for consumer in consumers:
            current.add(consumer, lifetime=Lifetime.SCOPED, scope=Scope.APP)
        assert len(current._providers_registrations) == provider_count
        assert current._root_resolver is None
        assert all(current._providers_registrations.find_by_type(key) is None for key in keys)
        gc.collect()
        return (current,), {}

    def compile_container(container: Container) -> None:
        container.compile()

    def teardown(container: Container) -> None:
        nonlocal current
        try:
            assert container._root_resolver is not None
            assert len(container._providers_registrations) == 2 * provider_count
            assert not any(
                spec.needs_cleanup for spec in container._providers_registrations.values()
            )
            for entity, key, consumer in zip(entities, keys, consumers, strict=True):
                instance: Any = container.resolve(consumer)
                assert instance.repo.entity_type is entity
                assert instance.repo is container.resolve(key)
                assert instance is container.resolve(consumer)
        finally:
            if container._root_resolver is not None:
                container.close()
            current = None

    benchmark.extra_info.update(
        consumer_count=provider_count,
        materialized_provider_count=provider_count,
        operation="cold generic compile; types, registrations and teardown excluded",
        gc_policy="enabled during compile; collect after registrations",
    )
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
        if current is not None:
            teardown(current)
