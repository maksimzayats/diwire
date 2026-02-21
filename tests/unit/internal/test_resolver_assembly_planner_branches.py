from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Annotated, Any, cast

import pytest

from diwire import Container, Lifetime, Provider, Scope
from diwire._internal.providers import ProviderDependency, ProviderSpec, ProvidersRegistrations
from diwire._internal.resolvers.assembly import planner as planner_module
from diwire._internal.resolvers.assembly.planner import ResolverGenerationPlanner
from diwire._internal.scope import BaseScope, BaseScopes
from diwire.exceptions import DIWireDependencyNotRegisteredError, DIWireInvalidProviderSpecError


def _planner() -> ResolverGenerationPlanner:
    container = Container()
    container.add_instance(1, provides=int)
    return ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )


def test_validate_scope_metadata_errors() -> None:
    with pytest.raises(DIWireInvalidProviderSpecError, match="expected BaseScope"):
        planner_module._validate_resolver_assembly_scope(cast("Any", object()))

    valid_scope = Scope.APP

    monkey = cast("Any", valid_scope)
    original_name = monkey.scope_name
    original_level = monkey.level
    try:
        monkey.scope_name = None
        with pytest.raises(DIWireInvalidProviderSpecError, match="missing 'scope_name'"):
            planner_module._validate_resolver_assembly_scope(valid_scope)

        monkey.scope_name = 1
        with pytest.raises(DIWireInvalidProviderSpecError, match="must be str"):
            planner_module._validate_resolver_assembly_scope(valid_scope)

        monkey.scope_name = "bad.name"
        with pytest.raises(DIWireInvalidProviderSpecError, match="not a valid identifier"):
            planner_module._validate_resolver_assembly_scope(valid_scope)

        monkey.scope_name = "for"
        with pytest.raises(DIWireInvalidProviderSpecError, match="Python keyword"):
            planner_module._validate_resolver_assembly_scope(valid_scope)

        monkey.scope_name = "APP"
        monkey.level = None
        with pytest.raises(DIWireInvalidProviderSpecError, match="missing 'level'"):
            planner_module._validate_resolver_assembly_scope_level(scope=valid_scope)

        monkey.level = "1"
        with pytest.raises(DIWireInvalidProviderSpecError, match="must be int"):
            planner_module._validate_resolver_assembly_scope_level(scope=valid_scope)
    finally:
        monkey.scope_name = original_name
        monkey.level = original_level


def test_validate_managed_scopes_owner_instantiation_error() -> None:
    class _BrokenOwner(BaseScopes):
        def __init__(self) -> None:
            msg = "boom"
            raise RuntimeError(msg)

    root_scope = BaseScope(1)
    cast("Any", root_scope).owner = _BrokenOwner
    with pytest.raises(DIWireInvalidProviderSpecError, match="instantiable"):
        planner_module.validate_resolver_assembly_managed_scopes(root_scope=root_scope)


def test_planner_resolve_provider_attribute_and_cache_owner_errors() -> None:
    planner = _planner()
    scope = Scope.APP

    spec_without_provider = ProviderSpec(
        provides=str,
        dependencies=[],
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        scope=scope,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(DIWireInvalidProviderSpecError, match="does not define a provider"):
        planner._resolve_provider_attribute(spec=spec_without_provider)

    transient_factory_spec = ProviderSpec(
        provides=float,
        factory=lambda: 1.0,
        dependencies=[],
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        scope=scope,
        lifetime=Lifetime.TRANSIENT,
    )

    with pytest.raises(DIWireInvalidProviderSpecError, match="Cannot resolve cache owner"):
        planner._cache_owner_scope_level(spec=transient_factory_spec, is_cached=True)


def test_planner_invalid_keyword_argument_name_error_branch() -> None:
    planner = _planner()
    fake_parameter = SimpleNamespace(kind=inspect.Parameter.KEYWORD_ONLY, name="bad-name")
    fake_dependency = SimpleNamespace(parameter=fake_parameter)

    with pytest.raises(DIWireInvalidProviderSpecError, match="not a valid identifier"):
        planner._format_dependency_argument_for_expression(
            dependency=cast("ProviderDependency", fake_dependency),
            expression="value",
        )


def test_planner_dependency_order_without_callable_returns_false() -> None:
    planner = _planner()
    dependency = ProviderDependency(
        provides=int,
        parameter=inspect.Parameter(
            name="value",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ),
    )
    spec = ProviderSpec(
        provides=bytes,
        instance=b"x",
        dependencies=[dependency],
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        scope=Scope.APP,
        lifetime=Lifetime.SCOPED,
    )

    assert planner._dependency_order_is_signature_order(spec=spec) is False


def test_planner_max_required_scope_cycle_guard_error() -> None:
    planner = _planner()
    spec = ProviderSpec(
        provides=tuple,
        instance=(),
        dependencies=[],
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        scope=Scope.APP,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(DIWireInvalidProviderSpecError, match="Circular dependency detected"):
        planner._resolve_max_required_scope_level(
            slot=spec.slot,
            by_slot={spec.slot: spec},
            max_scope_level_by_slot={},
            in_progress={spec.slot},
        )


def test_planner_missing_dependency_raises_from_provider_plan() -> None:
    class _Missing:
        pass

    class _Consumer:
        def __init__(self, dependency: _Missing) -> None:
            self.dependency = dependency

    registrations = ProvidersRegistrations()
    dependency = ProviderDependency(
        provides=_Missing,
        parameter=inspect.Parameter(
            name="dependency",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ),
    )
    registrations.add(
        ProviderSpec(
            provides=_Consumer,
            concrete_type=_Consumer,
            dependencies=[dependency],
            is_async=False,
            is_any_dependency_async=False,
            needs_cleanup=False,
            scope=Scope.APP,
            lifetime=Lifetime.SCOPED,
        ),
    )

    with pytest.raises(DIWireDependencyNotRegisteredError, match="is not registered"):
        ResolverGenerationPlanner(
            root_scope=Scope.APP,
            registrations=registrations,
        ).build()


def test_planner_dependency_order_out_of_signature_order_returns_false() -> None:
    planner = _planner()

    def _factory(first: int, second: int) -> int:
        return first + second

    dependencies = [
        ProviderDependency(
            provides=int,
            parameter=inspect.Parameter(
                name="second",
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ),
        ),
        ProviderDependency(
            provides=int,
            parameter=inspect.Parameter(
                name="first",
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ),
        ),
    ]
    spec = ProviderSpec(
        provides=int,
        factory=_factory,
        dependencies=dependencies,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        scope=Scope.APP,
        lifetime=Lifetime.SCOPED,
    )

    assert planner._dependency_order_is_signature_order(spec=spec) is False


def test_planner_provider_callable_for_generator_and_context_manager() -> None:
    planner = _planner()

    def _generator() -> Any:
        yield 1

    class _ContextManager:
        def __enter__(self) -> int:
            return 1

        def __exit__(self, *_args: object) -> None:
            return None

    def _context_manager() -> _ContextManager:
        return _ContextManager()

    generator_spec = ProviderSpec(
        provides=list,
        generator=_generator,
        dependencies=[],
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=True,
        scope=Scope.APP,
        lifetime=Lifetime.SCOPED,
    )
    context_manager_spec = ProviderSpec(
        provides=dict,
        context_manager=_context_manager,
        dependencies=[],
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=True,
        scope=Scope.APP,
        lifetime=Lifetime.SCOPED,
    )

    assert planner._provider_callable_for_signature(spec=generator_spec) is _generator
    assert planner._provider_callable_for_signature(spec=context_manager_spec) is _context_manager


def test_plan_provider_dependency_missing_required_uses_dependency_spec_error() -> None:
    planner = _planner()
    registration_spec = planner._registrations.get_by_type(int)
    dependency = ProviderDependency(
        provides=str,
        parameter=inspect.Parameter(
            name="dependency",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ),
    )

    with pytest.raises(DIWireDependencyNotRegisteredError, match="is not registered"):
        planner._plan_provider_dependency(
            spec=registration_spec,
            dependency_index=0,
            dependency=dependency,
            dependency_key=str,
            optional=False,
        )


def test_plan_provider_dependency_uses_normalized_key_fallback() -> None:
    planner = _planner()
    registration_spec = planner._registrations.get_by_type(int)
    dependency_key = Annotated[int, "meta"]
    dependency = ProviderDependency(
        provides=dependency_key,
        parameter=inspect.Parameter(
            name="dependency",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ),
    )

    _plan, dependency_slot, _requires_async, _sync_arg, _async_arg = (
        planner._plan_provider_dependency(
            spec=registration_spec,
            dependency_index=0,
            dependency=dependency,
            dependency_key=dependency_key,
            optional=False,
        )
    )

    assert dependency_slot == registration_spec.slot


def test_plan_provider_handle_dependency_uses_normalized_inner_key_fallback() -> None:
    planner = _planner()
    registration_spec = planner._registrations.get_by_type(int)
    dependency_key = Provider[Annotated[int, "meta"]]
    dependency = ProviderDependency(
        provides=dependency_key,
        parameter=inspect.Parameter(
            name="provider",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ),
    )

    plan, _dependency_slot, _requires_async, _sync_arg, _async_arg = (
        planner._plan_provider_handle_dependency(
            spec=registration_spec,
            dependency_index=0,
            dependency=dependency,
            dependency_key=dependency_key,
        )
    )

    assert plan.provider_inner_slot == registration_spec.slot


def test_dependency_slots_for_graph_uses_normalized_key_fallback() -> None:
    planner = _planner()
    dependency_key = Annotated[int, "meta"]
    dependency = ProviderDependency(
        provides=dependency_key,
        parameter=inspect.Parameter(
            name="dependency",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ),
    )

    slots = planner._dependency_slots_for_graph(
        dependency=dependency,
        requiring_provider=int,
    )

    assert slots == (planner._registrations.get_by_type(int).slot,)


def test_dependency_spec_or_error_uses_normalized_key_fallback() -> None:
    planner = _planner()

    dependency_spec = planner._dependency_spec_or_error(
        dependency_provides=Annotated[int, "meta"],
        requiring_provider=int,
    )

    assert dependency_spec.provides is int


def test_build_all_slots_by_key_includes_non_component_annotated_registrations() -> None:
    container = Container()
    container.add_instance(1, provides=Annotated[int, "meta"])
    container.add_instance(2, provides=int, component="primary")
    planner = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    slots_by_key = planner._build_all_slots_by_key()

    assert int in slots_by_key
    assert len(slots_by_key[int]) == 2
