from __future__ import annotations

import gc
from collections.abc import Generator
from dataclasses import make_dataclass
from typing import Any, cast

from diwire import Container, DependencyRegistrationPolicy, Lifetime, LockMode, MissingPolicy, Scope

_CHAIN_LENGTH = 32


class _Resource:
    def __init__(self) -> None:
        self.close_count = 0


def _provide_resource() -> Generator[_Resource, None, None]:
    resource = _Resource()
    try:
        yield resource
    finally:
        resource.close_count += 1


def test_benchmark_diwire_late_cleanup_registration(benchmark: Any) -> None:
    chain: list[type[object]] = []
    dependency: type[object] = _Resource
    for index in range(_CHAIN_LENGTH):
        dependency = make_dataclass(f"CleanupConsumer{index}", [("dependency", dependency)])
        chain.append(dependency)
    current: Container | None = None

    def setup() -> tuple[tuple[Container], dict[str, object]]:
        nonlocal current
        current = Container(
            missing_policy=MissingPolicy.ERROR,
            dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
            lock_mode=LockMode.NONE,
            use_resolver_context=False,
        )
        # Dependents precede dependencies, forcing repeated propagation passes.
        for consumer in reversed(chain):
            current.add(consumer, lifetime=Lifetime.SCOPED, scope=Scope.APP)
        assert len(current._providers_registrations) == _CHAIN_LENGTH
        assert not any(spec.needs_cleanup for spec in current._providers_registrations.values())
        assert current._providers_registrations.find_by_type(_Resource) is None
        assert current._root_resolver is None
        gc.collect()
        return (current,), {}

    def register(container: Container) -> None:
        container.add_generator(
            _provide_resource, provides=_Resource, lifetime=Lifetime.SCOPED, scope=Scope.APP
        )

    def teardown(container: Container) -> None:
        nonlocal current
        resource: _Resource | None = None
        try:
            assert container._root_resolver is None
            assert len(container._providers_registrations) == _CHAIN_LENGTH + 1
            assert all(spec.needs_cleanup for spec in container._providers_registrations.values())
            instance: Any = container.resolve(chain[-1])
            assert instance is container.resolve(chain[-1])
            for consumer in reversed(chain):
                assert isinstance(instance, consumer)
                instance = cast("Any", instance).dependency
            resource = container.resolve(_Resource)
            assert instance is resource
            assert resource.close_count == 0
        finally:
            if container._root_resolver is not None:
                container.close()
            current = None
        assert resource.close_count == 1

    benchmark.extra_info.update(
        dependency_count=_CHAIN_LENGTH,
        operation="late cleanup registration; chain setup, compile and teardown excluded",
        gc_policy="enabled during registration; collect after chain setup",
    )
    try:
        benchmark.pedantic(
            register, setup=setup, teardown=teardown, iterations=1, rounds=20, warmup_rounds=3
        )
    finally:
        if current is not None:
            teardown(current)
