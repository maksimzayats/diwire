from __future__ import annotations

import inspect
import runpy
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from importlib.metadata import PackageNotFoundError
from typing import Any, Literal, cast

import pytest

from diwire import Container, Lifetime, LockMode, Scope
from diwire._internal.providers import ProviderDependency, ProviderSpec, ProvidersRegistrations
from diwire._internal.resolvers.templates import renderer as renderer_module
from diwire._internal.resolvers.templates.planner import (
    ProviderDependencyPlan,
    ProviderWorkflowPlan,
    ResolverGenerationPlan,
    ResolverGenerationPlanner,
    ScopePlan,
    _validate_codegen_scope,
    _validate_codegen_scope_level,
)
from diwire._internal.resolvers.templates.renderer import (
    DependencyExpressionContext,
    ResolversTemplateRenderer,
)
from diwire._internal.scope import BaseScope
from diwire.exceptions import DIWireDependencyNotRegisteredError, DIWireInvalidProviderSpecError


class _Config:
    pass


class _Service:
    def __init__(self, config: _Config) -> None:
        self.config = config


class _AsyncService:
    def __init__(self, value: int) -> None:
        self.value = value


class _GeneratorService:
    pass


class _AsyncGeneratorService:
    pass


class _ContextManagerService:
    pass


class _AsyncContextManagerService:
    pass


class _AsyncDependencyConsumer:
    def __init__(self, dependency: _AsyncGeneratorService) -> None:
        self.dependency = dependency


class _DependencyShapeService:
    def __init__(
        self,
        positional: int,
        values: tuple[int, ...],
        options: dict[str, int],
    ) -> None:
        self.positional = positional
        self.values = values
        self.options = options


class _CycleA:
    pass


class _CycleB:
    pass


class _RequestRootOnlyService:
    pass


class _RequestRootSessionService:
    pass


class _MissingPlannerDependency:
    pass


async def _provide_int() -> int:
    return 42


async def _provide_async_service(value: int) -> _AsyncService:
    return _AsyncService(value)


def _provide_generator_service() -> Generator[_GeneratorService, None, None]:
    yield _GeneratorService()


async def _provide_async_generator_service() -> AsyncGenerator[_AsyncGeneratorService, None]:
    yield _AsyncGeneratorService()


@contextmanager
def _provide_context_manager_service() -> Generator[_ContextManagerService, None, None]:
    yield _ContextManagerService()


@asynccontextmanager
async def _provide_async_context_manager_service() -> AsyncGenerator[
    _AsyncContextManagerService,
    None,
]:
    yield _AsyncContextManagerService()


def _provide_dependency_shape_service(
    positional: int,
    /,
    *values: int,
    **options: int,
) -> _DependencyShapeService:
    return _DependencyShapeService(positional=positional, values=tuple(values), options=options)


def _provide_cycle_a(dep_b: _CycleB) -> _CycleA:
    return _CycleA()


def _provide_cycle_b(dep_a: _CycleA) -> _CycleB:
    return _CycleB()


def _make_workflow_plan(
    *,
    slot: int = 1,
    provides: object = int,
    provider_attribute: str = "instance",
    is_provider_async: bool = False,
    is_cached: bool = False,
    scope_level: int = Scope.APP.level,
    provider_is_inject_wrapper: bool = False,
    lock_mode: LockMode = LockMode.THREAD,
    effective_lock_mode: LockMode | None = None,
    requires_async: bool | None = None,
    uses_thread_lock: bool | None = None,
    uses_async_lock: bool | None = None,
    dispatch_kind: Literal["identity", "equality_map"] = "identity",
) -> ProviderWorkflowPlan:
    resolved_requires_async = is_provider_async if requires_async is None else requires_async
    resolved_effective_lock_mode = lock_mode if effective_lock_mode is None else effective_lock_mode
    resolved_uses_thread_lock = (
        is_cached
        and resolved_effective_lock_mode is LockMode.THREAD
        and not resolved_requires_async
        if uses_thread_lock is None
        else uses_thread_lock
    )
    resolved_uses_async_lock = (
        is_cached and resolved_effective_lock_mode is LockMode.ASYNC and resolved_requires_async
        if uses_async_lock is None
        else uses_async_lock
    )
    return ProviderWorkflowPlan(
        slot=slot,
        provides=provides,
        provider_attribute=provider_attribute,
        provider_reference=1,
        lifetime=Lifetime.TRANSIENT,
        scope_name="app",
        scope_level=scope_level,
        scope_attr_name="_app_resolver",
        is_cached=is_cached,
        is_transient=not is_cached,
        cache_owner_scope_level=Scope.APP.level if is_cached else None,
        lock_mode=lock_mode,
        effective_lock_mode=resolved_effective_lock_mode,
        uses_thread_lock=resolved_uses_thread_lock,
        uses_async_lock=resolved_uses_async_lock,
        is_provider_async=is_provider_async,
        requires_async=resolved_requires_async,
        needs_cleanup=False,
        dependencies=(),
        dependency_slots=(),
        dependency_requires_async=(),
        dependency_order_is_signature_order=True,
        max_required_scope_level=scope_level,
        dispatch_kind=dispatch_kind,
        sync_arguments=(),
        async_arguments=(),
        provider_is_inject_wrapper=provider_is_inject_wrapper,
    )


def _make_generation_plan(
    *,
    scopes: tuple[ScopePlan, ...],
    workflows: tuple[ProviderWorkflowPlan, ...],
    root_scope_level: int = Scope.APP.level,
    has_async_specs: bool = False,
    has_cleanup: bool = False,
) -> ResolverGenerationPlan:
    cached_provider_count = sum(1 for workflow in workflows if workflow.is_cached)
    thread_lock_count = sum(1 for workflow in workflows if workflow.uses_thread_lock)
    async_lock_count = sum(1 for workflow in workflows if workflow.uses_async_lock)
    identity_dispatch_slots = tuple(
        workflow.slot for workflow in workflows if workflow.dispatch_kind == "identity"
    )
    equality_dispatch_slots = tuple(
        workflow.slot for workflow in workflows if workflow.dispatch_kind == "equality_map"
    )
    return ResolverGenerationPlan(
        root_scope_level=root_scope_level,
        has_async_specs=has_async_specs,
        provider_count=len(workflows),
        cached_provider_count=cached_provider_count,
        thread_lock_count=thread_lock_count,
        async_lock_count=async_lock_count,
        effective_mode_counts=(
            (
                LockMode.THREAD,
                sum(1 for workflow in workflows if workflow.effective_lock_mode is LockMode.THREAD),
            ),
            (
                LockMode.ASYNC,
                sum(1 for workflow in workflows if workflow.effective_lock_mode is LockMode.ASYNC),
            ),
            (
                LockMode.NONE,
                sum(1 for workflow in workflows if workflow.effective_lock_mode is LockMode.NONE),
            ),
        ),
        has_cleanup=has_cleanup,
        identity_dispatch_slots=identity_dispatch_slots,
        equality_dispatch_slots=equality_dispatch_slots,
        scopes=scopes,
        workflows=workflows,
    )


def test_renderer_output_is_deterministic_and_composable() -> None:
    container = Container()
    container.add_instance(_Config(), provides=_Config)
    container.add_concrete(_Service, provides=_Service, lifetime=Lifetime.TRANSIENT)

    renderer = ResolversTemplateRenderer()
    code_first = renderer.get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )
    code_second = renderer.get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert code_first == code_second
    assert "class RootResolver:" in code_first
    assert "def build_root_resolver(" in code_first
    assert "ResolverProtocol" not in code_first
    assert ") -> RootResolver:" in code_first
    assert "def __enter__(self) -> RootResolver:" in code_first
    assert "async def __aenter__(self) -> RootResolver:" in code_first
    assert "def enter_scope(" in code_first
    assert "scope: Any | None = None," in code_first
    assert "context: Any | None = None," in code_first
    assert (
        ") -> RootResolver | _SessionResolver | _RequestResolver | _ActionResolver | _StepResolver:"
    ) in code_first
    assert ") -> NoReturn:" in code_first
    assert "def resolve(self, dependency: Any) -> Any:" in code_first
    assert "async def aresolve(self, dependency: Any) -> Any:" in code_first
    assert code_first.startswith('"""')
    assert (
        "Generated by: diwire._internal.resolvers.templates.renderer."
        "ResolversTemplateRenderer.get_providers_code"
    ) in code_first
    assert "diwire version used for generation:" in code_first
    assert "Generation configuration:" in code_first
    assert "Examples:" in code_first
    assert "Provider slot " in code_first
    assert "Returns: " in code_first
    assert "Provider spec kind: " in code_first
    assert "Dependency wiring:" in code_first
    assert "# Bind module-level globals to this container registration snapshot." in code_first
    assert (
        "# Capture dependency identity token used by `resolve`/`aresolve` dispatch." in code_first
    )


def test_renderer_output_avoids_reflective_hot_path_tokens() -> None:
    container = Container()
    container.add_instance(_Config(), provides=_Config)
    container.add_concrete(_Service, provides=_Service, lifetime=Lifetime.SCOPED)

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "getattr(" not in code
    assert "__dict__" in code
    assert "cast(" not in code


def test_renderer_logs_lock_strategy_once_per_compile_cache_miss(
    caplog: pytest.LogCaptureFixture,
) -> None:
    container = Container()
    container.add_factory(
        lambda: _Service(_Config()),
        provides=_Service,
        lifetime=Lifetime.SCOPED,
    )

    caplog.set_level("INFO", logger="diwire._internal.resolvers.templates.renderer")

    container.compile()
    container.compile()

    records = [
        record for record in caplog.records if "Resolver codegen strategy:" in record.getMessage()
    ]
    assert len(records) == 1


def test_planner_selects_async_effective_lock_mode_when_async_specs_exist() -> None:
    container = Container()
    container.add_factory(_provide_int, provides=int, lifetime=Lifetime.SCOPED)
    container.add_factory(
        _provide_async_service,
        provides=_AsyncService,
        lifetime=Lifetime.SCOPED,
    )

    plan = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    ).build()

    assert plan.has_async_specs is True
    assert all(workflow.effective_lock_mode is LockMode.ASYNC for workflow in plan.workflows)


def test_planner_rejects_non_identifier_scope_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container()
    monkeypatch.setattr(Scope.APP, "scope_name", "bad.name")

    with pytest.raises(DIWireInvalidProviderSpecError, match="scope_name"):
        ResolverGenerationPlanner(
            root_scope=Scope.APP,
            registrations=container._providers_registrations,
        )


def test_planner_rejects_keyword_scope_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container()
    monkeypatch.setattr(Scope.APP, "scope_name", "for")

    with pytest.raises(DIWireInvalidProviderSpecError, match="keyword"):
        ResolverGenerationPlanner(
            root_scope=Scope.APP,
            registrations=container._providers_registrations,
        )


def test_validate_codegen_scope_rejects_non_scope_member() -> None:
    with pytest.raises(DIWireInvalidProviderSpecError, match="BaseScope member"):
        _validate_codegen_scope(object())


def test_validate_codegen_scope_rejects_missing_scope_name() -> None:
    with pytest.raises(DIWireInvalidProviderSpecError, match="missing 'scope_name'"):
        _validate_codegen_scope(BaseScope(2))


def test_validate_codegen_scope_rejects_non_string_scope_name() -> None:
    invalid_scope = BaseScope(2)
    invalid_scope.scope_name = cast("Any", 10)

    with pytest.raises(DIWireInvalidProviderSpecError, match="'scope_name' must be str"):
        _validate_codegen_scope(invalid_scope)


def test_validate_codegen_scope_level_rejects_missing_level() -> None:
    invalid_scope = BaseScope(2)
    invalid_scope.scope_name = "request"
    del invalid_scope.level

    with pytest.raises(DIWireInvalidProviderSpecError, match="missing 'level'"):
        _validate_codegen_scope_level(scope=invalid_scope)


def test_validate_codegen_scope_level_rejects_non_int_level() -> None:
    invalid_scope = BaseScope(2)
    invalid_scope.scope_name = "request"
    invalid_scope.level = cast("Any", "two")

    with pytest.raises(DIWireInvalidProviderSpecError, match="'level' must be int"):
        _validate_codegen_scope_level(scope=invalid_scope)


def test_renderer_includes_generator_context_helpers_for_generator_graphs() -> None:
    container = Container()
    container.add_generator(
        _provide_generator_service,
        provides=_GeneratorService,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container.add_generator(
        _provide_async_generator_service,
        provides=_AsyncGeneratorService,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "from contextlib import asynccontextmanager, contextmanager" in code
    assert "contextmanager(_provider_" in code
    assert "value = _provider_cm.__enter__()" in code
    assert "value = next(_provider_gen)" in code
    assert "asynccontextmanager(_provider_" in code
    assert "value = await _provider_cm.__aenter__()" in code
    assert "value = await anext(_provider_gen)" in code


def test_renderer_does_not_add_generator_helpers_for_context_manager_only_graphs() -> None:
    container = Container()
    container.add_context_manager(
        _provide_context_manager_service,
        provides=_ContextManagerService,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "from contextlib import asynccontextmanager, contextmanager" not in code
    assert "value = _provider_cm.__enter__()" in code


def test_renderer_emits_async_context_manager_branch_for_async_context_manager_specs() -> None:
    container = Container()
    container.add_context_manager(
        _provide_async_context_manager_service,
        provides=_AsyncContextManagerService,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "value = await _provider_cm.__aenter__()" in code
    assert "provider_scope_resolver._cleanup_callbacks.append((1, _provider_cm.__aexit__))" in code
    assert "asynccontextmanager(_provider_" not in code


def test_renderer_dependency_wiring_supports_positional_varargs_and_varkw() -> None:
    signature = inspect.signature(_provide_dependency_shape_service)
    positional_type = int
    values_type = tuple[int, ...]
    options_type = dict[str, int]

    container = Container()
    container.add_instance(1, provides=positional_type)
    container.add_instance((2, 3), provides=values_type)
    container.add_instance({"first": 1, "second": 2}, provides=options_type)
    container.add_factory(
        _provide_dependency_shape_service,
        provides=_DependencyShapeService,
        dependencies={
            positional_type: signature.parameters["positional"],
            values_type: signature.parameters["values"],
            options_type: signature.parameters["options"],
        },
    )

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "positional=self.resolve_" not in code
    assert "*self." in code
    assert "**self." in code


def test_planner_classifies_dispatch_strategy_for_class_and_non_class_keys() -> None:
    container = Container()
    container.add_instance(1, provides=int)
    container.add_instance({"first": 1}, provides=dict[str, int])

    plan = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    ).build()

    workflow_by_type = {workflow.provides: workflow for workflow in plan.workflows}
    assert workflow_by_type[int].dispatch_kind == "identity"
    assert workflow_by_type[dict[str, int]].dispatch_kind == "equality_map"
    assert len(plan.identity_dispatch_slots) == 1
    assert len(plan.equality_dispatch_slots) == 1


def test_renderer_emits_equality_fallback_when_non_class_keys_exist() -> None:
    container = Container()
    container.add_instance(1, provides=int)
    container.add_instance({"first": 1}, provides=dict[str, int])

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "_dep_eq_slot_by_key: dict[Any, int] = {}" in code
    assert "_dep_eq_slot_by_key = {}" in code
    assert "_dep_eq_slot_by_key.get(dependency, _MISSING_DEP_SLOT)" in code
    assert "Then it performs one equality-map lookup for non-class dependency keys." in code


def test_renderer_omits_equality_fallback_for_pure_class_key_graphs() -> None:
    container = Container()
    container.add_instance(_Config(), provides=_Config)
    container.add_instance(_Service(_Config()), provides=_Service)

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "_dep_eq_slot_by_key" not in code
    assert "_MISSING_DEP_SLOT" not in code
    assert "equality-map lookup" not in code


def test_renderer_raises_for_circular_dependency_graph() -> None:
    container = Container()
    container.add_factory(_provide_cycle_a, provides=_CycleA)
    container.add_factory(_provide_cycle_b, provides=_CycleB)

    with pytest.raises(DIWireInvalidProviderSpecError, match="Circular dependency detected"):
        ResolversTemplateRenderer().get_providers_code(
            root_scope=Scope.APP,
            registrations=container._providers_registrations,
        )


def test_renderer_documents_instance_lifetime_from_container_default() -> None:
    container = Container(default_lifetime=Lifetime.SCOPED)
    container.add_instance(_Config(), provides=_Config)

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "Provider spec kind: instance" in code
    assert "Declared lifetime: singleton" in code


def test_renderer_filters_providers_and_scopes_when_root_scope_is_request() -> None:
    container = Container()
    container.add_concrete(
        _Config,
        provides=_Config,
        scope=Scope.APP,
        lifetime=Lifetime.SCOPED,
    )
    container.add_concrete(
        _RequestRootSessionService,
        provides=_RequestRootSessionService,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )
    container.add_concrete(
        _RequestRootOnlyService,
        provides=_RequestRootOnlyService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.REQUEST,
        registrations=container._providers_registrations,
    )

    assert "root scope level: 3" in code
    assert "managed scopes: request:3, action:4, step:5" in code
    assert "class _SessionResolver:" not in code
    assert "session:2" not in code
    assert "Provider target: " in code
    assert "_RequestRootOnlyService" in code


def test_planner_raises_for_provider_spec_without_provider_object() -> None:
    planner = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=ProvidersRegistrations(),
    )
    invalid_spec = ProviderSpec(
        provides=int,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
    )

    with pytest.raises(
        DIWireInvalidProviderSpecError,
        match="does not define a provider",
    ):
        planner._resolve_provider_attribute(spec=invalid_spec)


def test_planner_raises_for_unknown_cached_lifetime() -> None:
    planner = ResolverGenerationPlanner(
        root_scope=Scope.REQUEST,
        registrations=ProvidersRegistrations(),
    )
    spec = ProviderSpec(
        provides=int,
        lifetime=None,
        scope=Scope.ACTION,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
    )

    with pytest.raises(
        DIWireInvalidProviderSpecError,
        match="Cannot resolve cache owner",
    ):
        planner._cache_owner_scope_level(spec=spec, is_cached=True)


def test_planner_propagates_async_requirement_from_dependencies() -> None:
    def _build_sync_consumer(dependency: _AsyncGeneratorService) -> _AsyncDependencyConsumer:
        return _AsyncDependencyConsumer(dependency)

    container = Container()
    container.add_generator(
        _provide_async_generator_service,
        provides=_AsyncGeneratorService,
        lifetime=Lifetime.SCOPED,
    )
    container.add_factory(
        _build_sync_consumer,
        provides=_AsyncDependencyConsumer,
        lifetime=Lifetime.SCOPED,
    )

    plan = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    ).build()

    workflow_by_type = {workflow.provides: workflow for workflow in plan.workflows}
    assert workflow_by_type[_AsyncDependencyConsumer].requires_async is True


def test_planner_raises_for_missing_non_optional_dependency() -> None:
    def _build_service(_dependency: _MissingPlannerDependency) -> _Service:
        return _Service(config=_Config())

    container = Container(
        autoregister_concrete_types=False,
        autoregister_dependencies=False,
    )
    container.add_factory(
        _build_service,
        provides=_Service,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(DIWireDependencyNotRegisteredError, match="is not registered"):
        ResolverGenerationPlanner(
            root_scope=Scope.APP,
            registrations=container._providers_registrations,
        ).build()


def test_plan_provider_dependency_raises_via_non_optional_missing_lookup_path() -> None:
    planner = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=ProvidersRegistrations(),
    )
    dependency = ProviderDependency(
        provides=_MissingPlannerDependency,
        parameter=inspect.Parameter(
            "_dependency",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ),
    )
    spec = ProviderSpec(
        provides=_Service,
        factory=lambda: _Service(config=_Config()),
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
    )

    with pytest.raises(DIWireDependencyNotRegisteredError, match="is not registered"):
        planner._plan_provider_dependency(
            spec=spec,
            dependency_index=0,
            dependency=dependency,
            dependency_key=dependency.provides,
            optional=False,
        )


def test_planner_dependency_order_helpers_cover_edge_paths() -> None:
    planner = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=ProvidersRegistrations(),
    )
    signature = inspect.signature(_provide_dependency_shape_service)

    no_provider_spec = ProviderSpec(
        provides=_DependencyShapeService,
        instance=_DependencyShapeService(positional=1, values=(), options={}),
        lifetime=Lifetime.SCOPED,
        scope=Scope.APP,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[
            ProviderDependency(
                provides=int,
                parameter=signature.parameters["positional"],
            ),
        ],
    )
    assert planner._dependency_order_is_signature_order(spec=no_provider_spec) is False

    out_of_order_spec = ProviderSpec(
        provides=_DependencyShapeService,
        factory=_provide_dependency_shape_service,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[
            ProviderDependency(
                provides=dict[str, int],
                parameter=signature.parameters["options"],
            ),
            ProviderDependency(
                provides=int,
                parameter=signature.parameters["positional"],
            ),
        ],
    )
    assert planner._dependency_order_is_signature_order(spec=out_of_order_spec) is False

    generator_spec = ProviderSpec(
        provides=_GeneratorService,
        generator=_provide_generator_service,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=True,
    )
    context_spec = ProviderSpec(
        provides=_ContextManagerService,
        context_manager=_provide_context_manager_service,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=True,
    )
    missing_spec = ProviderSpec(
        provides=int,
        instance=1,
        lifetime=Lifetime.SCOPED,
        scope=Scope.APP,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
    )

    assert (
        planner._provider_callable_for_signature(spec=generator_spec) is _provide_generator_service
    )
    assert (
        planner._provider_callable_for_signature(spec=context_spec)
        is _provide_context_manager_service
    )
    assert planner._provider_callable_for_signature(spec=missing_spec) is None


def test_planner_max_required_scope_level_detects_cycles() -> None:
    planner = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=ProvidersRegistrations(),
    )
    spec = ProviderSpec(
        provides=int,
        instance=1,
        lifetime=Lifetime.SCOPED,
        scope=Scope.APP,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
    )

    with pytest.raises(DIWireInvalidProviderSpecError, match="Circular dependency detected"):
        planner._resolve_max_required_scope_level(
            slot=spec.slot,
            by_slot={spec.slot: spec},
            max_scope_level_by_slot={},
            in_progress={spec.slot},
        )


def test_renderer_enter_scope_raises_when_default_transition_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = ResolversTemplateRenderer()
    class_plan = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="app_resolver",
        resolver_attr_name="_app_resolver",
        skippable=False,
        is_root=True,
    )
    next_scope = ScopePlan(
        scope_name="session",
        scope_level=Scope.SESSION.level,
        class_name="_SessionResolver",
        resolver_arg_name="session_resolver",
        resolver_attr_name="_session_resolver",
        skippable=True,
        is_root=False,
    )
    plan = _make_generation_plan(scopes=(class_plan, next_scope), workflows=())
    monkeypatch.setattr(
        renderer,
        "_next_scope_options",
        lambda **_kwargs: (next_scope, None, (next_scope,)),
    )

    with pytest.raises(ValueError, match="Expected a default scope transition"):
        renderer._render_enter_scope_method(plan=plan, class_plan=class_plan)


def test_renderer_local_value_build_raises_for_unsupported_provider_attribute() -> None:
    renderer = ResolversTemplateRenderer()
    class_plan = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="app_resolver",
        resolver_attr_name="_app_resolver",
        skippable=False,
        is_root=True,
    )
    workflow = _make_workflow_plan(provider_attribute="unsupported")

    with pytest.raises(ValueError, match="Unsupported provider attribute"):
        renderer._render_local_value_build(
            workflow=workflow,
            is_async_call=False,
            class_plan=class_plan,
            scope_by_level={class_plan.scope_level: class_plan},
            workflow_by_slot={workflow.slot: workflow},
        )


def test_renderer_async_method_renders_non_locking_async_build_path() -> None:
    renderer = ResolversTemplateRenderer()
    class_plan = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="app_resolver",
        resolver_attr_name="_app_resolver",
        skippable=False,
        is_root=True,
    )
    workflow = _make_workflow_plan(
        provider_attribute="factory",
        is_provider_async=True,
        is_cached=False,
    )
    plan = _make_generation_plan(scopes=(class_plan,), workflows=(workflow,))

    method_code = renderer._render_async_method(
        plan=plan,
        class_plan=class_plan,
        scope_by_level={class_plan.scope_level: class_plan},
        workflow=workflow,
    )

    assert "async with _dep_1_async_lock:" not in method_code
    assert "value = await value" in method_code
    assert "return value" in method_code


def test_renderer_generator_build_rejects_sync_resolution_for_async_generator_provider() -> None:
    renderer = ResolversTemplateRenderer()
    workflow = _make_workflow_plan(
        provider_attribute="generator",
        is_provider_async=True,
    )

    with pytest.raises(ValueError, match="cannot be resolved synchronously"):
        renderer._render_generator_build(workflow=workflow, arguments=(), is_async_call=False)


def test_renderer_provider_scope_guard_returns_scope_mismatch_for_deeper_provider_scope() -> None:
    renderer = ResolversTemplateRenderer()
    workflow = _make_workflow_plan(scope_level=Scope.REQUEST.level)

    lines = renderer._render_provider_scope_guard(
        class_scope_level=Scope.APP.level,
        scope_by_level={},
        workflow=workflow,
    )

    assert "requires opened scope level" in "\n".join(lines)


def test_renderer_local_value_build_appends_await_for_async_factory_provider() -> None:
    renderer = ResolversTemplateRenderer()
    class_plan = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="app_resolver",
        resolver_attr_name="_app_resolver",
        skippable=False,
        is_root=True,
    )
    workflow = _make_workflow_plan(
        provider_attribute="factory",
        is_provider_async=True,
    )

    lines = renderer._render_local_value_build(
        workflow=workflow,
        is_async_call=True,
        class_plan=class_plan,
        scope_by_level={class_plan.scope_level: class_plan},
        workflow_by_slot={workflow.slot: workflow},
    )

    assert lines == ["value = _provider_1()", "value = await value"]


def test_renderer_local_value_build_passes_internal_resolver_to_inject_wrapper_provider() -> None:
    renderer = ResolversTemplateRenderer()
    class_plan = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="app_resolver",
        resolver_attr_name="_app_resolver",
        skippable=False,
        is_root=True,
    )
    workflow = _make_workflow_plan(
        provider_attribute="factory",
        provider_is_inject_wrapper=True,
    )

    lines = renderer._render_local_value_build(
        workflow=workflow,
        is_async_call=False,
        class_plan=class_plan,
        scope_by_level={class_plan.scope_level: class_plan},
        workflow_by_slot={workflow.slot: workflow},
    )

    assert lines == ["value = _provider_1(", "    diwire_resolver=self,", ")"]


def test_renderer_emits_resolver_kwarg_for_async_inject_wrapper() -> None:
    renderer = ResolversTemplateRenderer()
    class_plan = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="app_resolver",
        resolver_attr_name="_app_resolver",
        skippable=False,
        is_root=True,
    )
    workflow = _make_workflow_plan(
        provider_attribute="factory",
        is_provider_async=True,
        provider_is_inject_wrapper=True,
    )

    lines = renderer._render_local_value_build(
        workflow=workflow,
        is_async_call=True,
        class_plan=class_plan,
        scope_by_level={class_plan.scope_level: class_plan},
        workflow_by_slot={workflow.slot: workflow},
    )

    assert lines == [
        "value = _provider_1(",
        "    diwire_resolver=self,",
        ")",
        "value = await value",
    ]


def test_renderer_local_value_build_skips_internal_resolver_for_regular_provider() -> None:
    renderer = ResolversTemplateRenderer()
    class_plan = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="app_resolver",
        resolver_attr_name="_app_resolver",
        skippable=False,
        is_root=True,
    )
    workflow = _make_workflow_plan(
        provider_attribute="factory",
        provider_is_inject_wrapper=False,
    )

    lines = renderer._render_local_value_build(
        workflow=workflow,
        is_async_call=False,
        class_plan=class_plan,
        scope_by_level={class_plan.scope_level: class_plan},
        workflow_by_slot={workflow.slot: workflow},
    )

    assert lines == ["value = _provider_1()"]


def test_renderer_non_inject_provider_no_extra_kwarg() -> None:
    renderer = ResolversTemplateRenderer()
    class_plan = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="app_resolver",
        resolver_attr_name="_app_resolver",
        skippable=False,
        is_root=True,
    )
    workflow = _make_workflow_plan(
        provider_attribute="factory",
        is_provider_async=True,
        provider_is_inject_wrapper=False,
    )

    lines = renderer._render_local_value_build(
        workflow=workflow,
        is_async_call=True,
        class_plan=class_plan,
        scope_by_level={class_plan.scope_level: class_plan},
        workflow_by_slot={workflow.slot: workflow},
    )

    assert "diwire_resolver" not in "\n".join(lines)


def test_renderer_async_cache_replace_returns_empty_for_non_cached_workflow() -> None:
    renderer = ResolversTemplateRenderer()
    class_plan = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="app_resolver",
        resolver_attr_name="_app_resolver",
        skippable=False,
        is_root=True,
    )
    workflow = _make_workflow_plan(is_cached=False)
    plan = _make_generation_plan(scopes=(class_plan,), workflows=(workflow,))

    assert renderer._render_async_cache_replace(plan=plan, workflow=workflow) == []


def test_renderer_async_method_delegates_to_non_root_owner_for_async_workflow() -> None:
    renderer = ResolversTemplateRenderer()
    root_scope = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="app_resolver",
        resolver_attr_name="_app_resolver",
        skippable=False,
        is_root=True,
    )
    owner_scope = ScopePlan(
        scope_name="session",
        scope_level=Scope.SESSION.level,
        class_name="_SessionResolver",
        resolver_arg_name="session_resolver",
        resolver_attr_name="_session_resolver",
        skippable=True,
        is_root=False,
    )
    class_plan = ScopePlan(
        scope_name="request",
        scope_level=Scope.REQUEST.level,
        class_name="_RequestResolver",
        resolver_arg_name="request_resolver",
        resolver_attr_name="_request_resolver",
        skippable=False,
        is_root=False,
    )
    workflow = replace(
        _make_workflow_plan(
            provider_attribute="factory",
            is_provider_async=True,
            is_cached=False,
            scope_level=Scope.SESSION.level,
        ),
        scope_name="session",
        scope_attr_name="_session_resolver",
        requires_async=True,
        max_required_scope_level=Scope.SESSION.level,
    )
    plan = _make_generation_plan(
        scopes=(root_scope, owner_scope, class_plan),
        workflows=(workflow,),
    )

    method_code = renderer._render_async_method(
        plan=plan,
        class_plan=class_plan,
        scope_by_level={
            root_scope.scope_level: root_scope,
            owner_scope.scope_level: owner_scope,
            class_plan.scope_level: class_plan,
        },
        workflow=workflow,
    )

    assert "owner_resolver = self._session_resolver" in method_code
    assert "return await owner_resolver.aresolve_1()" in method_code


def test_renderer_provider_scope_guard_uses_owner_resolver_for_cleanup_providers() -> None:
    renderer = ResolversTemplateRenderer()
    owner_scope = ScopePlan(
        scope_name="session",
        scope_level=Scope.SESSION.level,
        class_name="_SessionResolver",
        resolver_arg_name="session_resolver",
        resolver_attr_name="_session_resolver",
        skippable=True,
        is_root=False,
    )
    workflow = replace(
        _make_workflow_plan(
            provider_attribute="generator",
            scope_level=Scope.SESSION.level,
        ),
        scope_name="session",
        scope_attr_name="_session_resolver",
    )

    lines = renderer._render_provider_scope_guard(
        class_scope_level=Scope.REQUEST.level,
        scope_by_level={Scope.SESSION.level: owner_scope},
        workflow=workflow,
    )

    assert lines[0] == "provider_scope_resolver = self._session_resolver"


def test_renderer_dependency_expression_delegates_to_root_scope_when_safe() -> None:
    renderer = ResolversTemplateRenderer()
    dependency_workflow = replace(
        _make_workflow_plan(
            slot=3,
            provider_attribute="factory",
            is_cached=False,
            scope_level=Scope.APP.level,
        ),
        max_required_scope_level=Scope.APP.level,
    )
    root_scope = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="app_resolver",
        resolver_attr_name="_app_resolver",
        skippable=False,
        is_root=True,
    )

    expression = renderer._dependency_expression_for_class(
        dependency_workflow=dependency_workflow,
        dependency_requires_async=False,
        is_async_call=False,
        context=DependencyExpressionContext(
            class_scope_level=Scope.REQUEST.level,
            root_scope=root_scope,
            workflow_by_slot={dependency_workflow.slot: dependency_workflow},
        ),
    )

    assert expression == "self._app_resolver.resolve_3()"


def test_inline_root_sync_dependency_expression_returns_none_for_non_callable_provider() -> None:
    renderer = ResolversTemplateRenderer()
    workflow = replace(
        _make_workflow_plan(
            slot=2,
            provider_attribute="instance",
            is_cached=False,
            scope_level=Scope.APP.level,
        ),
        max_required_scope_level=Scope.APP.level,
    )
    root_scope = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="root_resolver",
        resolver_attr_name="_root_resolver",
        skippable=False,
        is_root=True,
    )
    context = DependencyExpressionContext(
        class_scope_level=Scope.REQUEST.level,
        root_scope=root_scope,
        workflow_by_slot={workflow.slot: workflow},
    )

    assert (
        renderer._inline_root_sync_dependency_expression(
            dependency_workflow=workflow,
            dependency_requires_async=False,
            context=context,
            depth=0,
        )
        is None
    )


def test_inline_root_sync_dependency_expression_renders_factory_call() -> None:
    renderer = ResolversTemplateRenderer()
    workflow = replace(
        _make_workflow_plan(
            slot=5,
            provider_attribute="factory",
            is_cached=False,
            scope_level=Scope.APP.level,
        ),
        max_required_scope_level=Scope.APP.level,
    )
    root_scope = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="root_resolver",
        resolver_attr_name="_root_resolver",
        skippable=False,
        is_root=True,
    )
    context = DependencyExpressionContext(
        class_scope_level=Scope.REQUEST.level,
        root_scope=root_scope,
        workflow_by_slot={workflow.slot: workflow},
    )

    expression = renderer._inline_root_sync_dependency_expression(
        dependency_workflow=workflow,
        dependency_requires_async=False,
        context=context,
        depth=0,
    )

    assert expression == "_provider_5()"


def test_inline_root_sync_dependency_expression_appends_resolver_for_inject_wrapper() -> None:
    renderer = ResolversTemplateRenderer()
    workflow = replace(
        _make_workflow_plan(
            slot=5,
            provider_attribute="factory",
            is_cached=False,
            scope_level=Scope.APP.level,
            provider_is_inject_wrapper=True,
        ),
        max_required_scope_level=Scope.APP.level,
    )
    root_scope = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="root_resolver",
        resolver_attr_name="_root_resolver",
        skippable=False,
        is_root=True,
    )
    context = DependencyExpressionContext(
        class_scope_level=Scope.REQUEST.level,
        root_scope=root_scope,
        workflow_by_slot={workflow.slot: workflow},
    )

    expression = renderer._inline_root_sync_dependency_expression(
        dependency_workflow=workflow,
        dependency_requires_async=False,
        context=context,
        depth=0,
    )

    assert expression == "_provider_5(diwire_resolver=self._root_resolver)"


def test_renderer_emits_root_resolver_expression_for_inline_nested_inject_wrapper() -> None:
    renderer = ResolversTemplateRenderer()
    workflow = replace(
        _make_workflow_plan(
            slot=5,
            provider_attribute="factory",
            is_cached=False,
            scope_level=Scope.APP.level,
            provider_is_inject_wrapper=True,
        ),
        max_required_scope_level=Scope.APP.level,
    )
    root_scope = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="root_resolver",
        resolver_attr_name="_root_resolver",
        skippable=False,
        is_root=True,
    )
    context = DependencyExpressionContext(
        class_scope_level=Scope.REQUEST.level,
        root_scope=root_scope,
        workflow_by_slot={workflow.slot: workflow},
    )

    expression = renderer._inline_root_nested_dependency_expression(
        slot=workflow.slot,
        requires_async=False,
        context=context,
        depth=0,
    )

    assert expression == "_provider_5(diwire_resolver=self._root_resolver)"


def test_append_internal_resolver_argument_inserts_before_var_keyword_dependency() -> None:
    renderer = ResolversTemplateRenderer()
    arguments = ["dependency", "**resolved_options"]

    renderer._append_internal_resolver_argument(
        arguments=arguments,
        resolver_expression="self",
    )

    assert arguments == ["dependency", "diwire_resolver=self", "**resolved_options"]


def test_renderer_places_internal_resolver_before_varkw() -> None:
    renderer = ResolversTemplateRenderer()
    arguments = ["dependency", "**resolved_options"]

    renderer._append_internal_resolver_argument(
        arguments=arguments,
        resolver_expression="self",
    )

    assert arguments == ["dependency", "diwire_resolver=self", "**resolved_options"]


def test_renderer_format_dependency_argument_raises_for_invalid_keyword_parameter_name() -> None:
    class _FakeParameter:
        def __init__(self) -> None:
            self.name = "bad.name"
            self.kind = inspect.Parameter.POSITIONAL_OR_KEYWORD

    renderer = ResolversTemplateRenderer()
    dependency = ProviderDependency(
        provides=int,
        parameter=cast("Any", _FakeParameter()),
    )

    with pytest.raises(DIWireInvalidProviderSpecError, match="not a valid identifier"):
        renderer._format_dependency_argument(
            dependency=dependency,
            expression="self.resolve_1()",
            prefer_positional=False,
        )


def test_planner_format_dependency_argument_raises_for_invalid_keyword_parameter_name() -> None:
    class _FakeParameter:
        def __init__(self) -> None:
            self.name = "bad.name"
            self.kind = inspect.Parameter.POSITIONAL_OR_KEYWORD

    planner = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=ProvidersRegistrations(),
    )
    dependency = ProviderDependency(
        provides=int,
        parameter=cast("Any", _FakeParameter()),
    )

    with pytest.raises(DIWireInvalidProviderSpecError, match="not a valid identifier"):
        planner._format_dependency_argument(
            dependency=dependency,
            dependency_slot=1,
            dependency_requires_async=False,
            is_async_call=False,
        )


def test_inline_root_nested_dependency_expression_falls_back_to_root_resolve() -> None:
    renderer = ResolversTemplateRenderer()
    signature = inspect.signature(_provide_dependency_shape_service)
    dependency = ProviderDependency(
        provides=int,
        parameter=signature.parameters["positional"],
    )
    parent_workflow = replace(
        _make_workflow_plan(
            slot=1,
            provider_attribute="factory",
            is_cached=False,
            scope_level=Scope.APP.level,
        ),
        max_required_scope_level=Scope.APP.level,
        dependencies=(dependency,),
        dependency_slots=(2,),
        dependency_requires_async=(False,),
        dependency_order_is_signature_order=True,
    )
    nested_workflow = replace(
        _make_workflow_plan(
            slot=2,
            provider_attribute="instance",
            is_cached=False,
            scope_level=Scope.APP.level,
        ),
        max_required_scope_level=Scope.APP.level,
    )
    root_scope = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="root_resolver",
        resolver_attr_name="_root_resolver",
        skippable=False,
        is_root=True,
    )
    context = DependencyExpressionContext(
        class_scope_level=Scope.REQUEST.level,
        root_scope=root_scope,
        workflow_by_slot={
            parent_workflow.slot: parent_workflow,
            nested_workflow.slot: nested_workflow,
        },
    )

    expression = renderer._inline_root_nested_dependency_expression(
        slot=nested_workflow.slot,
        requires_async=False,
        context=context,
        depth=0,
    )

    assert expression == "self._root_resolver.resolve_2()"


def test_inline_root_sync_dependency_expression_returns_none_when_argument_inlining_fails() -> None:
    renderer = ResolversTemplateRenderer()
    signature = inspect.signature(_provide_dependency_shape_service)
    dependency = ProviderDependency(
        provides=int,
        parameter=signature.parameters["positional"],
    )
    parent_workflow = replace(
        _make_workflow_plan(
            slot=7,
            provider_attribute="factory",
            is_cached=False,
            scope_level=Scope.APP.level,
        ),
        max_required_scope_level=Scope.APP.level,
        dependencies=(dependency,),
        dependency_slots=(8,),
        dependency_requires_async=(True,),
        dependency_order_is_signature_order=True,
    )
    nested_workflow = replace(
        _make_workflow_plan(
            slot=8,
            provider_attribute="instance",
            is_cached=False,
            scope_level=Scope.APP.level,
        ),
        max_required_scope_level=Scope.APP.level,
    )
    root_scope = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="root_resolver",
        resolver_attr_name="_root_resolver",
        skippable=False,
        is_root=True,
    )
    context = DependencyExpressionContext(
        class_scope_level=Scope.REQUEST.level,
        root_scope=root_scope,
        workflow_by_slot={
            parent_workflow.slot: parent_workflow,
            nested_workflow.slot: nested_workflow,
        },
    )

    expression = renderer._inline_root_sync_dependency_expression(
        dependency_workflow=parent_workflow,
        dependency_requires_async=False,
        context=context,
        depth=0,
    )

    assert expression is None


def test_inline_root_nested_dependency_expression_returns_inlined_expression_when_available() -> (
    None
):
    renderer = ResolversTemplateRenderer()
    nested_workflow = replace(
        _make_workflow_plan(
            slot=4,
            provider_attribute="factory",
            is_cached=False,
            scope_level=Scope.APP.level,
        ),
        max_required_scope_level=Scope.APP.level,
    )
    root_scope = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="root_resolver",
        resolver_attr_name="_root_resolver",
        skippable=False,
        is_root=True,
    )
    context = DependencyExpressionContext(
        class_scope_level=Scope.REQUEST.level,
        root_scope=root_scope,
        workflow_by_slot={nested_workflow.slot: nested_workflow},
    )

    expression = renderer._inline_root_nested_dependency_expression(
        slot=nested_workflow.slot,
        requires_async=False,
        context=context,
        depth=0,
    )

    assert expression == "_provider_4()"


def test_inline_root_nested_dependency_expression_returns_none_for_scope_mismatch() -> None:
    renderer = ResolversTemplateRenderer()
    nested_workflow = replace(
        _make_workflow_plan(
            slot=6,
            provider_attribute="instance",
            is_cached=False,
            scope_level=Scope.SESSION.level,
        ),
        max_required_scope_level=Scope.SESSION.level,
    )
    root_scope = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="root_resolver",
        resolver_attr_name="_root_resolver",
        skippable=False,
        is_root=True,
    )
    context = DependencyExpressionContext(
        class_scope_level=Scope.REQUEST.level,
        root_scope=root_scope,
        workflow_by_slot={nested_workflow.slot: nested_workflow},
    )

    expression = renderer._inline_root_nested_dependency_expression(
        slot=nested_workflow.slot,
        requires_async=False,
        context=context,
        depth=0,
    )

    assert expression is None


def test_inline_root_nested_dependency_expression_returns_none_for_root_scope_limit_and_async() -> (
    None
):
    renderer = ResolversTemplateRenderer()
    nested_workflow = replace(
        _make_workflow_plan(
            slot=9,
            provider_attribute="instance",
            is_cached=False,
            scope_level=Scope.APP.level,
        ),
        max_required_scope_level=Scope.SESSION.level,
    )
    root_scope = ScopePlan(
        scope_name="app",
        scope_level=Scope.APP.level,
        class_name="RootResolver",
        resolver_arg_name="root_resolver",
        resolver_attr_name="_root_resolver",
        skippable=False,
        is_root=True,
    )
    context = DependencyExpressionContext(
        class_scope_level=Scope.REQUEST.level,
        root_scope=root_scope,
        workflow_by_slot={nested_workflow.slot: nested_workflow},
    )

    async_expression = renderer._inline_root_nested_dependency_expression(
        slot=nested_workflow.slot,
        requires_async=True,
        context=context,
        depth=0,
    )
    root_limit_expression = renderer._inline_root_nested_dependency_expression(
        slot=nested_workflow.slot,
        requires_async=False,
        context=context,
        depth=0,
    )

    assert async_expression is None
    assert root_limit_expression is None


def test_renderer_format_lifetime_returns_none_when_workflow_has_no_lifetime() -> None:
    renderer = ResolversTemplateRenderer()
    workflow = replace(_make_workflow_plan(), lifetime=None)

    assert renderer._format_lifetime(workflow=workflow) == "none"


def test_renderer_resolve_diwire_version_returns_unknown_when_package_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_missing(_dist_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(renderer_module, "version", _raise_missing)

    assert ResolversTemplateRenderer()._resolve_diwire_version() == "unknown"


def test_renderer_format_symbol_pointer_repr_falls_back_to_runtime_type_name() -> None:
    class _PointerLike:
        def __str__(self) -> str:
            return "<_PointerLike object at 0xDEADBEEF>"

    renderer = ResolversTemplateRenderer()
    pointer_like = _PointerLike()

    assert renderer._format_symbol(pointer_like) == (
        f"{_PointerLike.__module__}.{_PointerLike.__qualname__}"
    )


def test_renderer_format_symbol_returns_text_for_non_pointer_repr() -> None:
    class _TextOnly:
        def __str__(self) -> str:
            return "text-only-symbol"

    renderer = ResolversTemplateRenderer()

    assert renderer._format_symbol(_TextOnly()) == "text-only-symbol"


def test_renderer_unique_ordered_filters_duplicates_without_reordering() -> None:
    renderer = ResolversTemplateRenderer()

    assert renderer._unique_ordered(["root", "request", "root", "session", "request"]) == [
        "root",
        "request",
        "session",
    ]


def test_render_build_function_raises_for_context_dependency_without_key_binding() -> None:
    renderer = ResolversTemplateRenderer()
    parameter = inspect.Parameter(
        "value",
        kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    dependency = ProviderDependency(provides=int, parameter=parameter)
    workflow = replace(
        _make_workflow_plan(slot=1),
        dependencies=(dependency,),
        dependency_plans=(
            ProviderDependencyPlan(
                kind="context",
                dependency=dependency,
                dependency_index=0,
                ctx_key_global_name=None,
            ),
        ),
    )
    plan = _make_generation_plan(
        scopes=(
            ScopePlan(
                scope_name="app",
                scope_level=Scope.APP.level,
                class_name="RootResolver",
                resolver_arg_name="root_resolver",
                resolver_attr_name="_root_resolver",
                skippable=False,
                is_root=True,
            ),
        ),
        workflows=(workflow,),
    )

    with pytest.raises(ValueError, match="missing global key name"):
        renderer._render_build_function(plan=plan)


def test_renderer_module_entrypoint_prints_generated_module(
    capsys: pytest.CaptureFixture[str],
) -> None:
    renderer_file = renderer_module.__file__
    assert renderer_file is not None
    runpy.run_path(renderer_file, run_name="__main__")

    captured = capsys.readouterr()
    assert "def build_root_resolver(" in captured.out
