from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from diwire.container import Container
from diwire.exceptions import DIWireInvalidProviderSpecError
from diwire.providers import Lifetime, ProviderSpec
from diwire.resolvers.templates.renderer import ResolversTemplateRenderer
from diwire.scope import Scope

_SEEDS = (3, 7, 13, 31, 71)


def _make_node_type(*, name: str, dependency_type: type[Any] | None) -> type[Any]:
    if dependency_type is None:

        def _init(self: Any) -> None:
            self.dependency = None

        return type(name, (), {"__init__": _init})

    def _init_with_dependency(self: Any, dependency: Any) -> None:
        self.dependency = dependency

    _init_with_dependency.__annotations__ = {
        "dependency": dependency_type,
        "return": None,
    }
    return type(name, (), {"__init__": _init_with_dependency})


def _build_random_container(
    seed: int,
    *,
    node_count: int = 9,
) -> tuple[Container, type[Any], Lifetime]:
    state = seed
    container = Container()
    node_types: list[type[Any]] = []
    target_lifetime = Lifetime.TRANSIENT

    for index in range(node_count):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        dependency_type = (
            node_types[state % len(node_types)] if node_types and state % 10 < 7 else None
        )
        node_type = _make_node_type(
            name=f"_FuzzNode_{seed}_{index}",
            dependency_type=dependency_type,
        )
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        lifetime = (Lifetime.TRANSIENT, Lifetime.SCOPED)[state % 2]
        container.register_concrete(
            node_type,
            concrete_type=node_type,
            lifetime=lifetime,
            scope=Scope.APP,
        )
        node_types.append(node_type)
        target_lifetime = lifetime

    return container, node_types[-1], target_lifetime


@pytest.mark.parametrize("seed", _SEEDS)
def test_fuzz_codegen_is_deterministic_for_same_seed(seed: int) -> None:
    slot_counter = ProviderSpec.SLOT_COUNTER
    try:
        ProviderSpec.SLOT_COUNTER = 0
        first_container, _, _ = _build_random_container(seed)
        first_code = ResolversTemplateRenderer().get_providers_code(
            root_scope=Scope.APP,
            registrations=first_container._providers_registrations,
        )

        ProviderSpec.SLOT_COUNTER = 0
        second_container, _, _ = _build_random_container(seed)
        second_code = ResolversTemplateRenderer().get_providers_code(
            root_scope=Scope.APP,
            registrations=second_container._providers_registrations,
        )
    finally:
        ProviderSpec.SLOT_COUNTER = slot_counter

    assert first_code == second_code


@pytest.mark.parametrize("seed", _SEEDS)
def test_fuzz_resolution_consistency_matches_top_level_lifetime(seed: int) -> None:
    container, target_type, target_lifetime = _build_random_container(seed)

    first = container.resolve(target_type)
    second = container.resolve(target_type)
    async_resolved = asyncio.run(container.aresolve(target_type))

    assert isinstance(first, target_type)
    assert isinstance(second, target_type)
    assert isinstance(async_resolved, target_type)

    if target_lifetime is Lifetime.TRANSIENT:
        assert first is not second
    else:
        assert first is second
        assert async_resolved is first


def test_fuzz_codegen_raises_for_cycle_graph() -> None:
    class _CycleA:
        pass

    class _CycleB:
        pass

    def _init_cycle_a(self: Any, dependency: Any) -> None:
        self.dependency = dependency

    def _init_cycle_b(self: Any, dependency: Any) -> None:
        self.dependency = dependency

    _init_cycle_a.__annotations__ = {"dependency": _CycleB, "return": None}
    _init_cycle_b.__annotations__ = {"dependency": _CycleA, "return": None}
    _CycleA.__init__ = cast("Any", _init_cycle_a)  # type: ignore[method-assign]
    _CycleB.__init__ = cast("Any", _init_cycle_b)  # type: ignore[method-assign]

    container = Container()
    container.register_concrete(_CycleA, concrete_type=_CycleA, lifetime=Lifetime.SCOPED)
    container.register_concrete(_CycleB, concrete_type=_CycleB, lifetime=Lifetime.SCOPED)

    with pytest.raises(DIWireInvalidProviderSpecError, match="Circular dependency detected"):
        ResolversTemplateRenderer().get_providers_code(
            root_scope=Scope.APP,
            registrations=container._providers_registrations,
        )
