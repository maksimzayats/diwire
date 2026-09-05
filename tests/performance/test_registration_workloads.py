from __future__ import annotations

import gc
from dataclasses import make_dataclass
from typing import Any, cast

import pytest

from diwire import Container, DependencyRegistrationPolicy, Lifetime, LockMode, MissingPolicy, Scope

_DEPENDENCY_COUNT = 16


def _registration_types(kind: str) -> tuple[type[object], tuple[type[object], ...]]:
    if kind == "settings":
        settings = pytest.importorskip("pydantic_settings")
        base = cast("type[object]", settings.BaseSettings)
        dependencies = tuple(
            type(
                f"Settings{index}",
                (base,),
                {
                    "__module__": __name__,
                    "__annotations__": {"probe_value": int},
                    "probe_value": 7,
                    "model_config": {"env_prefix": "DIWIRE_PERF_H007_"},
                },
            )
            for index in range(_DEPENDENCY_COUNT)
        )
    else:
        dependencies = tuple(type(f"Service{index}", (), {}) for index in range(_DEPENDENCY_COUNT))
    root = make_dataclass(
        "RegistrationRoot",
        [(f"dependency_{index}", dependency) for index, dependency in enumerate(dependencies)],
    )
    return root, dependencies


@pytest.mark.parametrize("kind", ["plain", "settings"])
def test_benchmark_diwire_warm_recursive_registration(benchmark: Any, kind: str) -> None:
    root, dependencies = _registration_types(kind)
    # This guard measures repeated inspection after optional integration initialization.
    warmup = Container(missing_policy=MissingPolicy.REGISTER_ROOT)
    try:
        assert isinstance(warmup.resolve(dependencies[0]), dependencies[0])
    finally:
        warmup.close()
    current: Container | None = None

    def setup() -> tuple[tuple[Container], dict[str, object]]:
        nonlocal current
        gc.collect()
        current = Container(
            missing_policy=MissingPolicy.ERROR,
            dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
            lock_mode=LockMode.NONE,
            use_resolver_context=False,
        )
        return (current,), {}

    def register(container: Container) -> None:
        container.add(root, scope=Scope.APP, lifetime=Lifetime.SCOPED)

    def teardown(container: Container) -> None:
        nonlocal current
        try:
            assert container._root_resolver is None
            for dependency in (root, *dependencies):
                registration = container._providers_registrations.get_by_type(dependency)
                assert registration.scope is Scope.APP
                assert registration.lifetime is Lifetime.SCOPED
                if kind == "settings" and dependency is not root:
                    assert registration.factory is not None
            first = container.resolve(root)
            assert first is container.resolve(root)
            for index, dependency in enumerate(dependencies):
                assert isinstance(getattr(first, f"dependency_{index}"), dependency)
        finally:
            container.close()
            current = None

    benchmark.extra_info.update(
        dependency_count=_DEPENDENCY_COUNT,
        kind=kind,
        operation="warm recursive registration; type/container setup and compile excluded",
        gc_policy="enabled during registration; collect before setup",
    )
    try:
        benchmark.pedantic(
            register, setup=setup, teardown=teardown, iterations=1, rounds=20, warmup_rounds=3
        )
    finally:
        if current is not None:
            teardown(current)
