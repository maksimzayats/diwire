from __future__ import annotations

import inspect
import runpy
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from importlib.metadata import PackageNotFoundError

import pytest

from diwire.container import Container
from diwire.exceptions import DIWireInvalidProviderSpecError
from diwire.providers import Lifetime, ProviderDependency, ProviderSpec, ProvidersRegistrations
from diwire.resolvers.templates import renderer as renderer_module
from diwire.resolvers.templates.planner import (
    LockMode,
    ProviderWorkflowPlan,
    ResolverGenerationPlan,
    ResolverGenerationPlanner,
    ScopePlan,
)
from diwire.resolvers.templates.renderer import (
    ResolversTemplateRenderer,
)
from diwire.scope import Scope


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
    provider_attribute: str = "instance",
    is_provider_async: bool = False,
    is_cached: bool = False,
    scope_level: int = Scope.APP.level,
) -> ProviderWorkflowPlan:
    return ProviderWorkflowPlan(
        slot=slot,
        provides=int,
        provider_attribute=provider_attribute,
        provider_reference=1,
        lifetime=Lifetime.TRANSIENT,
        scope_name="app",
        scope_level=scope_level,
        scope_attr_name="_app_resolver",
        is_cached=is_cached,
        is_transient=not is_cached,
        cache_owner_scope_level=Scope.APP.level if is_cached else None,
        concurrency_safe=True,
        is_provider_async=is_provider_async,
        requires_async=is_provider_async,
        needs_cleanup=False,
        dependencies=(),
        dependency_slots=(),
        dependency_requires_async=(),
        dependency_order_is_signature_order=True,
        max_required_scope_level=scope_level,
        sync_arguments=(),
        async_arguments=(),
    )


def test_renderer_output_is_deterministic_and_composable() -> None:
    container = Container()
    container.register_instance(_Config, instance=_Config())
    container.register_concrete(_Service, concrete_type=_Service, lifetime=Lifetime.TRANSIENT)

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
    assert (
        "def enter_scope(self, scope: Any | None = None) -> "
        "RootResolver | _SessionResolver | _RequestResolver:"
    ) in code_first
    assert "def enter_scope(self, scope: Any | None = None) -> NoReturn:" in code_first
    assert "def resolve(self, dependency: Any) -> Any:" in code_first
    assert "async def aresolve(self, dependency: Any) -> Any:" in code_first
    assert code_first.startswith('"""')
    assert (
        "Generated by: diwire.resolvers.templates.renderer."
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
    container.register_instance(_Config, instance=_Config())
    container.register_concrete(_Service, concrete_type=_Service, lifetime=Lifetime.SINGLETON)

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "getattr(" not in code
    assert "__dict__" in code
    assert "cast(" not in code


def test_planner_selects_async_lock_mode_when_async_specs_exist() -> None:
    container = Container()
    container.register_factory(int, factory=_provide_int, lifetime=Lifetime.SINGLETON)
    container.register_factory(
        _AsyncService,
        factory=_provide_async_service,
        lifetime=Lifetime.SINGLETON,
    )

    plan = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    ).build()

    assert plan.lock_mode is LockMode.ASYNC


def test_renderer_includes_generator_context_helpers_for_generator_graphs() -> None:
    container = Container()
    container.register_generator(
        _GeneratorService,
        generator=_provide_generator_service,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container.register_generator(
        _AsyncGeneratorService,
        generator=_provide_async_generator_service,
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
    container.register_context_manager(
        _ContextManagerService,
        context_manager=_provide_context_manager_service,
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
    container.register_context_manager(
        _AsyncContextManagerService,
        context_manager=_provide_async_context_manager_service,
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
    container.register_instance(provides=positional_type, instance=1)
    container.register_instance(provides=values_type, instance=(2, 3))
    container.register_instance(provides=options_type, instance={"first": 1, "second": 2})
    container.register_factory(
        _DependencyShapeService,
        factory=_provide_dependency_shape_service,
        dependencies=[
            ProviderDependency(
                provides=positional_type,
                parameter=signature.parameters["positional"],
            ),
            ProviderDependency(
                provides=values_type,
                parameter=signature.parameters["values"],
            ),
            ProviderDependency(
                provides=options_type,
                parameter=signature.parameters["options"],
            ),
        ],
    )

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "positional=self.resolve_" not in code
    assert "*self." in code
    assert "**self." in code


def test_renderer_raises_for_circular_dependency_graph() -> None:
    container = Container()
    container.register_factory(_CycleA, factory=_provide_cycle_a)
    container.register_factory(_CycleB, factory=_provide_cycle_b)

    with pytest.raises(DIWireInvalidProviderSpecError, match="Circular dependency detected"):
        ResolversTemplateRenderer().get_providers_code(
            root_scope=Scope.APP,
            registrations=container._providers_registrations,
        )


def test_renderer_documents_instance_lifetime_from_container_default() -> None:
    container = Container(default_lifetime=Lifetime.SINGLETON)
    container.register_instance(provides=_Config, instance=_Config())

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "Provider spec kind: instance" in code
    assert "Declared lifetime: singleton" in code


def test_renderer_filters_providers_and_scopes_when_root_scope_is_request() -> None:
    container = Container()
    container.register_concrete(
        _Config,
        concrete_type=_Config,
        scope=Scope.APP,
        lifetime=Lifetime.SINGLETON,
    )
    container.register_concrete(
        _RequestRootSessionService,
        concrete_type=_RequestRootSessionService,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _RequestRootOnlyService,
        concrete_type=_RequestRootOnlyService,
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


def test_planner_cache_owner_falls_back_to_root_scope_for_unknown_cached_lifetime() -> None:
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

    assert planner._cache_owner_scope_level(spec=spec, is_cached=True) == Scope.REQUEST.level


def test_planner_propagates_async_requirement_from_dependencies() -> None:
    def _build_sync_consumer(dependency: _AsyncGeneratorService) -> _AsyncDependencyConsumer:
        return _AsyncDependencyConsumer(dependency)

    container = Container()
    container.register_generator(
        _AsyncGeneratorService,
        generator=_provide_async_generator_service,
        lifetime=Lifetime.SINGLETON,
    )
    container.register_factory(
        _AsyncDependencyConsumer,
        factory=_build_sync_consumer,
        lifetime=Lifetime.SINGLETON,
    )

    plan = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    ).build()

    workflow_by_type = {workflow.provides: workflow for workflow in plan.workflows}
    assert workflow_by_type[_AsyncDependencyConsumer].requires_async is True


def test_planner_dependency_order_helpers_cover_edge_paths() -> None:
    planner = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=ProvidersRegistrations(),
    )
    signature = inspect.signature(_provide_dependency_shape_service)

    no_provider_spec = ProviderSpec(
        provides=_DependencyShapeService,
        instance=_DependencyShapeService(positional=1, values=(), options={}),
        lifetime=Lifetime.SINGLETON,
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
        lifetime=Lifetime.SINGLETON,
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
        lifetime=Lifetime.SINGLETON,
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
    plan = ResolverGenerationPlan(
        root_scope_level=Scope.APP.level,
        lock_mode=LockMode.THREAD,
        has_cleanup=False,
        scopes=(class_plan, next_scope),
        workflows=(),
    )
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
    plan = ResolverGenerationPlan(
        root_scope_level=Scope.APP.level,
        lock_mode=LockMode.ASYNC,
        has_cleanup=False,
        scopes=(class_plan,),
        workflows=(workflow,),
    )

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
    plan = ResolverGenerationPlan(
        root_scope_level=Scope.APP.level,
        lock_mode=LockMode.ASYNC,
        has_cleanup=False,
        scopes=(class_plan,),
        workflows=(workflow,),
    )

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
    plan = ResolverGenerationPlan(
        root_scope_level=Scope.APP.level,
        lock_mode=LockMode.ASYNC,
        has_cleanup=False,
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
        class_scope_level=Scope.REQUEST.level,
        root_scope=root_scope,
    )

    assert expression == "self._app_resolver.resolve_3()"


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


def test_renderer_module_entrypoint_prints_generated_module(
    capsys: pytest.CaptureFixture[str],
) -> None:
    renderer_file = renderer_module.__file__
    assert renderer_file is not None
    runpy.run_path(renderer_file, run_name="__main__")

    captured = capsys.readouterr()
    assert "def build_root_resolver(" in captured.out
