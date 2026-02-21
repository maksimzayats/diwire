from __future__ import annotations

import asyncio
import inspect
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Annotated, Any, cast

import pytest

from diwire import All, AsyncProvider, Container, FromContext, Lifetime, Maybe, Provider, Scope
from diwire._internal.lock_mode import LockMode
from diwire._internal.providers import ProviderDependency
from diwire._internal.resolvers.assembly import compiler as compiler_module
from diwire._internal.resolvers.assembly.planner import (
    ProviderDependencyPlan,
    ProviderWorkflowPlan,
    ResolverGenerationPlan,
    ResolverGenerationPlanner,
    ScopePlan,
)
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireDependencyNotRegisteredError,
    DIWireScopeMismatchError,
)


def _dependency(
    *,
    provides: Any = int,
    name: str = "value",
    kind: inspect._ParameterKind = inspect.Parameter.POSITIONAL_OR_KEYWORD,
    default: Any = inspect.Parameter.empty,
) -> ProviderDependency:
    return ProviderDependency(
        provides=provides,
        parameter=inspect.Parameter(name=name, kind=kind, default=default),
    )


def _scope_plan(*, level: int, name: str, skippable: bool = False) -> ScopePlan:
    is_root = level == Scope.APP.level
    return ScopePlan(
        scope_name=name,
        scope_level=level,
        class_name="RootResolver" if is_root else f"_{name.capitalize()}Resolver",
        resolver_arg_name="root_resolver" if is_root else f"{name}_resolver",
        resolver_attr_name="_root_resolver" if is_root else f"_{name}_resolver",
        skippable=skippable,
        is_root=is_root,
    )


def _workflow_plan(
    *,
    slot: int,
    provides: Any = int,
    provider_attribute: str = "instance",
    scope_level: int = Scope.APP.level,
    is_cached: bool = True,
    cache_owner_scope_level: int | None = Scope.APP.level,
    requires_async: bool = False,
    is_provider_async: bool = False,
    uses_thread_lock: bool = False,
    uses_async_lock: bool = False,
    dependencies: tuple[ProviderDependency, ...] = (),
    dependency_slots: tuple[int | None, ...] = (),
    dependency_requires_async: tuple[bool, ...] = (),
    dependency_plans: tuple[ProviderDependencyPlan, ...] = (),
    dispatch_kind: str = "identity",
    provider_is_inject_wrapper: bool = False,
    max_required_scope_level: int | None = None,
) -> ProviderWorkflowPlan:
    if max_required_scope_level is None:
        max_required_scope_level = scope_level
    return ProviderWorkflowPlan(
        slot=slot,
        provides=provides,
        provider_attribute=provider_attribute,
        provider_reference=object(),
        lifetime=Lifetime.SCOPED,
        scope_name="app" if scope_level == Scope.APP.level else "request",
        scope_level=scope_level,
        scope_attr_name="_root_resolver" if scope_level == Scope.APP.level else "_request_resolver",
        is_cached=is_cached,
        is_transient=not is_cached,
        cache_owner_scope_level=cache_owner_scope_level if is_cached else None,
        lock_mode=LockMode.THREAD,
        effective_lock_mode=LockMode.THREAD,
        uses_thread_lock=uses_thread_lock,
        uses_async_lock=uses_async_lock,
        is_provider_async=is_provider_async,
        requires_async=requires_async,
        needs_cleanup=provider_attribute in {"generator", "context_manager"},
        dependencies=dependencies,
        dependency_slots=dependency_slots,
        dependency_requires_async=dependency_requires_async,
        dependency_order_is_signature_order=True,
        max_required_scope_level=max_required_scope_level,
        dispatch_kind=cast("Any", dispatch_kind),
        sync_arguments=(),
        async_arguments=(),
        provider_is_inject_wrapper=provider_is_inject_wrapper,
        dependency_plans=dependency_plans,
    )


def _generation_plan(
    *,
    scopes: tuple[ScopePlan, ...],
    workflows: tuple[ProviderWorkflowPlan, ...],
    root_scope_level: int = Scope.APP.level,
    has_cleanup: bool = False,
) -> ResolverGenerationPlan:
    return ResolverGenerationPlan(
        root_scope_level=root_scope_level,
        has_async_specs=any(workflow.requires_async for workflow in workflows),
        provider_count=len(workflows),
        cached_provider_count=sum(1 for workflow in workflows if workflow.is_cached),
        thread_lock_count=sum(1 for workflow in workflows if workflow.uses_thread_lock),
        async_lock_count=sum(1 for workflow in workflows if workflow.uses_async_lock),
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
        identity_dispatch_slots=tuple(
            workflow.slot for workflow in workflows if workflow.dispatch_kind == "identity"
        ),
        equality_dispatch_slots=tuple(
            workflow.slot for workflow in workflows if workflow.dispatch_kind == "equality_map"
        ),
        scopes=scopes,
        workflows=workflows,
    )


def _runtime(
    *,
    scopes: tuple[ScopePlan, ...],
    workflows: tuple[ProviderWorkflowPlan, ...],
    provider_by_slot: dict[int, Any] | None = None,
    dep_type_by_slot: dict[int, Any] | None = None,
    all_slots_by_key: dict[Any, tuple[int, ...]] | None = None,
    dep_eq_slot_by_key: dict[Any, int] | None = None,
    context_key_by_name: dict[str, Any] | None = None,
    uses_stateless_scope_reuse: bool = False,
) -> compiler_module._ResolverRuntime:
    plan = _generation_plan(
        scopes=scopes,
        workflows=workflows,
        root_scope_level=scopes[0].scope_level,
        has_cleanup=True,
    )
    cache_slots_by_owner_level_mut: dict[int, list[int]] = {}
    for workflow in workflows:
        if workflow.is_cached and workflow.cache_owner_scope_level is not None:
            cache_slots_by_owner_level_mut.setdefault(workflow.cache_owner_scope_level, []).append(
                workflow.slot,
            )
    cache_slots_by_owner_level = {
        level: tuple(slots) for level, slots in cache_slots_by_owner_level_mut.items()
    }
    scope_obj_by_level = {scope.scope_level: scope.scope_level for scope in scopes}
    next_scope_options_by_level: dict[
        int,
        tuple[ScopePlan | None, ScopePlan | None, tuple[ScopePlan, ...]],
    ] = {}
    for scope in scopes:
        deeper_scopes = tuple(
            candidate for candidate in scopes if candidate.scope_level > scope.scope_level
        )
        if not deeper_scopes:
            next_scope_options_by_level[scope.scope_level] = (None, None, ())
            continue
        immediate_next = deeper_scopes[0]
        default_next = next(
            (candidate for candidate in deeper_scopes if not candidate.skippable), immediate_next
        )
        next_scope_options_by_level[scope.scope_level] = (
            immediate_next,
            default_next,
            deeper_scopes,
        )
    return compiler_module._ResolverRuntime(
        plan=plan,
        ordered_scopes=scopes,
        scopes_by_level={scope.scope_level: scope for scope in scopes},
        workflows_by_slot={workflow.slot: workflow for workflow in workflows},
        class_by_level={},
        root_scope=scopes[0],
        root_scope_level=scopes[0].scope_level,
        scope_obj_by_level=scope_obj_by_level,
        scope_level_by_scope_id={
            id(scope_obj): level for level, scope_obj in scope_obj_by_level.items()
        },
        uses_stateless_scope_reuse=uses_stateless_scope_reuse,
        has_cleanup=True,
        dep_registered_keys=set(),
        all_slots_by_key={} if all_slots_by_key is None else all_slots_by_key,
        dep_eq_slot_by_key={} if dep_eq_slot_by_key is None else dep_eq_slot_by_key,
        dep_type_by_slot={workflow.slot: workflow.provides for workflow in workflows}
        if dep_type_by_slot is None
        else dep_type_by_slot,
        provider_by_slot={workflow.slot: object() for workflow in workflows}
        if provider_by_slot is None
        else provider_by_slot,
        context_key_by_name={} if context_key_by_name is None else context_key_by_name,
        thread_lock_by_slot={
            workflow.slot: threading.Lock() for workflow in workflows if workflow.uses_thread_lock
        },
        async_lock_by_slot={
            workflow.slot: asyncio.Lock() for workflow in workflows if workflow.uses_async_lock
        },
        cache_slots_by_owner_level=cache_slots_by_owner_level,
        next_scope_options_by_level=next_scope_options_by_level,
    )


def test_extract_function_code_raises_for_missing_function() -> None:
    module_code = compile(
        "def outer():\n    def inner():\n        return 1\n    return inner\n",
        "<t>",
        "exec",
    )
    with pytest.raises(RuntimeError, match="Unable to extract"):
        compiler_module._extract_function_code(module_code=module_code, name="missing")


def test_compiler_enter_scope_error_and_deep_chain_branches() -> None:
    container = Container()

    class _RequestOnly:
        pass

    container.add(
        _RequestOnly, provides=_RequestOnly, scope=Scope.REQUEST, lifetime=Lifetime.SCOPED
    )
    root = cast(
        "Any",
        compiler_module.ResolversAssemblyCompiler().build_root_resolver(
            root_scope=Scope.APP,
            registrations=container._providers_registrations,
        ),
    )

    with pytest.raises(DIWireScopeMismatchError, match="not a valid next transition"):
        root.enter_scope(999)

    deep = root.enter_scope(Scope.STEP, context={int: 1})
    assert deep._owned_scope_resolvers


def test_compiler_stateless_scope_reuse_branches() -> None:
    container = Container()
    container.add_instance(1, provides=int)

    root = cast(
        "Any",
        compiler_module.ResolversAssemblyCompiler().build_root_resolver(
            root_scope=Scope.APP,
            registrations=container._providers_registrations,
        ),
    )

    reused = root.enter_scope(Scope.SESSION)
    assert reused is root._scope_resolver_2

    contextual = root.enter_scope(Scope.REQUEST, context={int: 1})
    assert contextual is not root._scope_resolver_3


def test_resolver_exit_captures_owned_scope_errors() -> None:
    owned = SimpleNamespace(
        __exit__=lambda *_args: (_ for _ in ()).throw(RuntimeError("owned boom")),
    )
    resolver = SimpleNamespace(
        _cleanup_callbacks=[],
        _owned_scope_resolvers=(owned,),
    )

    with pytest.raises(RuntimeError, match="owned boom"):
        compiler_module._resolver_exit(resolver, None, None, None)


@pytest.mark.asyncio
async def test_resolver_aexit_captures_owned_scope_errors() -> None:
    async def _boom(*_args: Any) -> None:
        msg = "owned async boom"
        raise RuntimeError(msg)

    owned = SimpleNamespace(__aexit__=_boom)
    resolver = SimpleNamespace(
        _cleanup_callbacks=[],
        _owned_scope_resolvers=(owned,),
    )

    with pytest.raises(RuntimeError, match="owned async boom"):
        await compiler_module._resolver_aexit(resolver, None, None, None)


@pytest.mark.asyncio
async def test_dispatch_fallback_async_and_sync_branches() -> None:
    runtime = SimpleNamespace(all_slots_by_key={int: (1,)})

    class _Resolver:
        _runtime = runtime

        def __init__(self) -> None:
            self.context: dict[Any, Any] = {}

        def resolve(self, dependency: Any) -> Any:
            return dependency

        async def aresolve(self, dependency: Any) -> Any:
            return dependency

        async def aresolve_1(self) -> int:
            return 11

        def resolve_1(self) -> int:
            return 11

        def _is_registered_dependency(self, dependency: Any) -> bool:
            return dependency is int

        def _resolve_from_context(self, key: Any) -> Any:
            if key in self.context:
                return self.context[key]
            msg = "missing"
            raise DIWireDependencyNotRegisteredError(msg)

    resolver = _Resolver()

    sync_provider = compiler_module._resolve_dispatch_fallback_sync(resolver, Provider[int])
    assert callable(sync_provider)

    async_provider = await compiler_module._resolve_dispatch_fallback_async(
        resolver,
        Maybe[AsyncProvider[int]],
    )
    assert callable(async_provider)

    assert (
        compiler_module._resolve_dispatch_fallback_sync(resolver, Maybe[FromContext[int]]) is None
    )
    assert (
        await compiler_module._resolve_dispatch_fallback_async(
            resolver,
            Maybe[FromContext[int]],
        )
        is None
    )
    assert compiler_module._resolve_dispatch_fallback_sync(resolver, Maybe[str]) is None
    assert await compiler_module._resolve_dispatch_fallback_async(resolver, Maybe[str]) is None

    assert compiler_module._resolve_dispatch_fallback_sync(resolver, All[int]) == (11,)
    assert await compiler_module._resolve_dispatch_fallback_async(resolver, All[int]) == (11,)

    with pytest.raises(DIWireDependencyNotRegisteredError):
        compiler_module._resolve_dispatch_fallback_sync(resolver, object())
    with pytest.raises(DIWireDependencyNotRegisteredError):
        await compiler_module._resolve_dispatch_fallback_async(resolver, object())


def test_build_local_value_sync_error_branches() -> None:
    workflow = _workflow_plan(slot=1, provider_attribute="generator", is_provider_async=True)
    runtime = _runtime(scopes=(_scope_plan(level=1, name="app"),), workflows=(workflow,))
    runtime.provider_by_slot[1] = lambda: iter([1])

    with pytest.raises(DIWireAsyncDependencyInSyncContextError):
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=SimpleNamespace(_cleanup_enabled=False),
            workflow=workflow,
            provider_scope_resolver=SimpleNamespace(_cleanup_callbacks=[]),
        )

    unsupported = replace(workflow, provider_attribute="unsupported")
    with pytest.raises(ValueError, match="Unsupported provider attribute"):
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=SimpleNamespace(_cleanup_enabled=False),
            workflow=unsupported,
            provider_scope_resolver=SimpleNamespace(_cleanup_callbacks=[]),
        )


@pytest.mark.asyncio
async def test_build_local_value_async_branches() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def _async_cm() -> Any:
        events.append("enter")
        yield 42
        events.append("exit")

    workflow = _workflow_plan(slot=1, provider_attribute="context_manager", is_provider_async=True)
    runtime = _runtime(scopes=(_scope_plan(level=1, name="app"),), workflows=(workflow,))
    runtime.provider_by_slot[1] = _async_cm

    resolver = SimpleNamespace(_cleanup_enabled=True)
    scope_resolver = SimpleNamespace(_cleanup_callbacks=[])

    value = await compiler_module._build_local_value_async(
        runtime=runtime,
        resolver=resolver,
        workflow=workflow,
        provider_scope_resolver=scope_resolver,
    )
    assert value == 42
    assert scope_resolver._cleanup_callbacks

    unsupported = replace(workflow, provider_attribute="unsupported")
    with pytest.raises(ValueError, match="Unsupported provider attribute"):
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver,
            workflow=unsupported,
            provider_scope_resolver=scope_resolver,
        )


def test_argument_and_dependency_error_branches() -> None:
    dependency = _dependency()
    missing_handle = ProviderDependencyPlan(
        kind="provider_handle",
        dependency=dependency,
        dependency_index=0,
    )
    missing_context = ProviderDependencyPlan(
        kind="context",
        dependency=dependency,
        dependency_index=0,
        ctx_key_global_name=None,
    )
    missing_slot = ProviderDependencyPlan(
        kind="provider",
        dependency=dependency,
        dependency_index=0,
        dependency_slot=None,
    )

    runtime = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(),
    )

    with pytest.raises(ValueError, match="provider inner slot"):
        compiler_module._resolve_dependency_value_sync(
            runtime=runtime,
            resolver=SimpleNamespace(),
            dependency_plan=missing_handle,
        )
    with pytest.raises(ValueError, match="context key global name"):
        compiler_module._resolve_dependency_value_sync(
            runtime=runtime,
            resolver=SimpleNamespace(),
            dependency_plan=missing_context,
        )
    with pytest.raises(ValueError, match="missing dependency slot"):
        compiler_module._resolve_dependency_value_sync(
            runtime=runtime,
            resolver=SimpleNamespace(),
            dependency_plan=missing_slot,
        )

    with pytest.raises(ValueError, match="Unsupported literal"):
        compiler_module._literal_value_for_plan(
            dependency_plan=ProviderDependencyPlan(
                kind="literal",
                dependency=dependency,
                dependency_index=0,
                literal_expression="bad",
            ),
        )


@pytest.mark.asyncio
async def test_async_dependency_error_branches() -> None:
    dependency = _dependency()
    missing_handle = ProviderDependencyPlan(
        kind="provider_handle",
        dependency=dependency,
        dependency_index=0,
    )

    runtime = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(),
    )

    with pytest.raises(ValueError, match="provider inner slot"):
        await compiler_module._resolve_dependency_value_async(
            runtime=runtime,
            resolver=SimpleNamespace(),
            dependency_plan=missing_handle,
        )


def test_call_provider_and_cache_replace_branches() -> None:
    with pytest.raises(TypeError, match="duplicate keyword"):
        compiler_module._call_provider(
            callable_obj=lambda **_kwargs: None,
            argument_parts=[
                compiler_module._ArgumentPart(kind="kw", name="x", value=1),
                compiler_module._ArgumentPart(kind="kw", name="x", value=2),
            ],
        )

    with pytest.raises(TypeError, match="duplicate keyword"):
        compiler_module._call_provider(
            callable_obj=lambda **_kwargs: None,
            argument_parts=[
                compiler_module._ArgumentPart(kind="kw", name="x", value=1),
                compiler_module._ArgumentPart(kind="starstar", value={"x": 2}),
            ],
        )

    root_scope = _scope_plan(level=1, name="app")
    workflow = _workflow_plan(slot=1, is_cached=True)
    runtime = _runtime(scopes=(root_scope,), workflows=(workflow,))
    resolver = SimpleNamespace()

    compiler_module._replace_sync_cache(
        runtime=runtime,
        resolver=resolver,
        workflow=workflow,
        value=5,
    )
    assert resolver.resolve_1() == 5
    assert asyncio.run(cast("Any", resolver.aresolve_1)()) == 5

    compiler_module._replace_async_cache(
        runtime=runtime,
        resolver=resolver,
        workflow=workflow,
        value=7,
    )
    assert asyncio.run(cast("Any", resolver.aresolve_1)()) == 7


def test_provider_scope_and_owner_resolver_branches() -> None:
    root_scope = _scope_plan(level=1, name="app")
    request_scope = _scope_plan(level=3, name="request")
    runtime = _runtime(
        scopes=(root_scope, request_scope),
        workflows=(),
    )

    deeper_workflow = _workflow_plan(slot=1, scope_level=3, provider_attribute="generator")
    with pytest.raises(DIWireScopeMismatchError):
        compiler_module._provider_scope_resolver_for_workflow(
            runtime=runtime,
            resolver=SimpleNamespace(),
            class_scope_level=1,
            workflow=deeper_workflow,
        )

    resolver = SimpleNamespace(
        _root_resolver="root", _request_resolver=compiler_module._MISSING_RESOLVER
    )
    assert (
        compiler_module._owner_resolver_for_scope(
            runtime=runtime,
            resolver=resolver,
            scope_level=1,
            workflow=_workflow_plan(slot=2),
        )
        == "root"
    )

    with pytest.raises(DIWireScopeMismatchError):
        compiler_module._owner_resolver_for_scope(
            runtime=runtime,
            resolver=resolver,
            scope_level=3,
            workflow=_workflow_plan(slot=2, scope_level=3),
        )


def test_dependency_plans_fallback_and_unique_ordered() -> None:
    fallback_workflow = _workflow_plan(
        slot=1,
        dependencies=(_dependency(name="a"), _dependency(name="b")),
        dependency_slots=(1, None),
        dependency_requires_async=(False, False),
        dependency_plans=(),
    )

    plans = compiler_module._dependency_plans_for_workflow(workflow=fallback_workflow)
    assert plans[0].kind == "provider"
    assert plans[1].kind == "context"

    assert compiler_module._unique_ordered(["a", "a", "b"]) == ["a", "b"]


def test_bootstrap_runtime_handles_missing_context_key_name() -> None:
    container = Container()
    container.add_instance(1, provides=int)
    registrations = container._providers_registrations
    compiler = compiler_module.ResolversAssemblyCompiler()
    slot = registrations.get_by_type(int).slot

    workflow = _workflow_plan(
        slot=slot,
        provides=int,
        dependency_plans=(
            ProviderDependencyPlan(
                kind="context",
                dependency=_dependency(provides=FromContext[int]),
                dependency_index=0,
                ctx_key_global_name=None,
            ),
        ),
    )
    plan = _generation_plan(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(workflow,),
    )

    runtime = compiler._bootstrap_runtime(
        plan=plan, registrations=registrations, root_scope=Scope.APP
    )
    assert runtime.context_key_by_name == {}


def test_bootstrap_runtime_normalizes_context_key_metadata() -> None:
    def build(value: FromContext[Annotated[int, "meta"]]) -> int:
        return value

    container = Container()
    container.add_factory(
        build,
        provides=int,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )
    registrations = container._providers_registrations
    compiler = compiler_module.ResolversAssemblyCompiler()
    slot = registrations.get_by_type(int).slot

    workflow = _workflow_plan(
        slot=slot,
        provides=int,
        dependency_plans=(
            ProviderDependencyPlan(
                kind="context",
                dependency=_dependency(provides=FromContext[Annotated[int, "meta"]]),
                dependency_index=0,
                ctx_key_global_name="_ctx_0_0_key",
            ),
        ),
    )
    plan = _generation_plan(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(workflow,),
    )

    runtime = compiler._bootstrap_runtime(
        plan=plan,
        registrations=registrations,
        root_scope=Scope.APP,
    )
    assert runtime.context_key_by_name["_ctx_0_0_key"] is int


def test_awaitable_in_sync_raises_for_awaitable_values() -> None:
    async def _value() -> int:
        return 1

    coro = _value()
    try:
        with pytest.raises(DIWireAsyncDependencyInSyncContextError):
            compiler_module._awaitable_in_sync(value=coro, slot=1)
    finally:
        coro.close()


def test_awaitable_in_sync_returns_non_awaitable() -> None:
    assert compiler_module._awaitable_in_sync(value=1, slot=1) == 1


def test_build_local_value_sync_additional_error_paths() -> None:
    resolver = SimpleNamespace(_cleanup_enabled=False)
    runtime = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(),
        provider_by_slot={},
    )

    async_workflow = _workflow_plan(
        slot=2,
        provider_attribute="factory",
        is_provider_async=True,
        is_cached=False,
    )

    class _AwaitableValue:
        def __await__(self) -> Any:
            return iter(())

    def _build_awaitable_value() -> _AwaitableValue:
        return _AwaitableValue()

    runtime.provider_by_slot[2] = _build_awaitable_value
    with pytest.raises(DIWireAsyncDependencyInSyncContextError):
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver,
            workflow=async_workflow,
            provider_scope_resolver=SimpleNamespace(_cleanup_callbacks=[]),
        )

    generator_workflow = _workflow_plan(slot=3, provider_attribute="generator", is_cached=False)
    runtime.provider_by_slot[3] = lambda: iter([1])
    with pytest.raises(DIWireScopeMismatchError):
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver,
            workflow=generator_workflow,
            provider_scope_resolver=compiler_module._MISSING_RESOLVER,
        )

    context_workflow = _workflow_plan(
        slot=4,
        provider_attribute="context_manager",
        is_provider_async=True,
        is_cached=False,
    )

    def _build_object() -> object:
        return object()

    runtime.provider_by_slot[4] = _build_object
    with pytest.raises(DIWireScopeMismatchError):
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver,
            workflow=context_workflow,
            provider_scope_resolver=compiler_module._MISSING_RESOLVER,
        )
    with pytest.raises(DIWireAsyncDependencyInSyncContextError):
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver,
            workflow=context_workflow,
            provider_scope_resolver=SimpleNamespace(_cleanup_callbacks=[]),
        )


@pytest.mark.asyncio
async def test_build_local_value_async_additional_paths() -> None:
    async def _agen() -> Any:
        yield 5

    def _sgen() -> Any:
        yield 6

    @asynccontextmanager
    async def _acm() -> Any:
        yield 7

    class _SyncCM:
        def __enter__(self) -> int:
            return 8

        def __exit__(self, *_args: object) -> None:
            return None

    runtime = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(),
        provider_by_slot={},
    )
    resolver = SimpleNamespace(_cleanup_enabled=False)
    scope_resolver = SimpleNamespace(_cleanup_callbacks=[])

    workflow_async_gen = _workflow_plan(
        slot=5,
        provider_attribute="generator",
        is_provider_async=True,
        is_cached=False,
    )
    runtime.provider_by_slot[5] = _agen
    assert (
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver,
            workflow=workflow_async_gen,
            provider_scope_resolver=scope_resolver,
        )
        == 5
    )

    workflow_sync_gen = _workflow_plan(
        slot=6,
        provider_attribute="generator",
        is_provider_async=False,
        is_cached=False,
    )
    runtime.provider_by_slot[6] = _sgen
    assert (
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver,
            workflow=workflow_sync_gen,
            provider_scope_resolver=scope_resolver,
        )
        == 6
    )

    with pytest.raises(DIWireScopeMismatchError):
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver,
            workflow=workflow_sync_gen,
            provider_scope_resolver=compiler_module._MISSING_RESOLVER,
        )

    workflow_async_cm = _workflow_plan(
        slot=7,
        provider_attribute="context_manager",
        is_provider_async=True,
        is_cached=False,
    )
    runtime.provider_by_slot[7] = _acm
    assert (
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver,
            workflow=workflow_async_cm,
            provider_scope_resolver=scope_resolver,
        )
        == 7
    )

    workflow_sync_cm = _workflow_plan(
        slot=8,
        provider_attribute="context_manager",
        is_provider_async=False,
        is_cached=False,
    )
    runtime.provider_by_slot[8] = _SyncCM
    assert (
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=SimpleNamespace(_cleanup_enabled=True),
            workflow=workflow_sync_cm,
            provider_scope_resolver=scope_resolver,
        )
        == 8
    )
    assert scope_resolver._cleanup_callbacks

    with pytest.raises(DIWireScopeMismatchError):
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver,
            workflow=workflow_sync_cm,
            provider_scope_resolver=compiler_module._MISSING_RESOLVER,
        )


@pytest.mark.asyncio
async def test_async_slot_impl_uncovered_branches() -> None:
    root_scope = _scope_plan(level=1, name="app")
    request_scope = _scope_plan(level=3, name="request")

    mismatch_workflow = _workflow_plan(
        slot=1,
        scope_level=3,
        requires_async=True,
        is_cached=True,
        cache_owner_scope_level=3,
    )
    runtime_mismatch = _runtime(scopes=(root_scope, request_scope), workflows=(mismatch_workflow,))
    resolver_type = type(
        "MismatchResolver", (), {"_runtime": runtime_mismatch, "_class_plan": root_scope}
    )
    resolver_mismatch = resolver_type()
    resolver_mismatch._root_resolver = SimpleNamespace()
    resolver_mismatch._cleanup_enabled = True
    resolver_mismatch._context = None
    resolver_mismatch._parent_context_resolver = None

    with pytest.raises(DIWireScopeMismatchError):
        await compiler_module._build_async_slot_impl(workflow=mismatch_workflow)(resolver_mismatch)

    delegated_workflow = _workflow_plan(
        slot=2,
        scope_level=1,
        max_required_scope_level=1,
        requires_async=True,
        is_cached=False,
    )
    runtime_delegated = _runtime(
        scopes=(root_scope, request_scope), workflows=(delegated_workflow,)
    )

    async def _owner_aresolve() -> str:
        return "delegated"

    root_owner = SimpleNamespace(aresolve_2=_owner_aresolve)
    request_resolver_type = type(
        "RequestResolver",
        (),
        {"_runtime": runtime_delegated, "_class_plan": request_scope},
    )
    request_resolver = request_resolver_type()
    request_resolver._root_resolver = root_owner
    request_resolver._cleanup_enabled = True
    request_resolver._context = None
    request_resolver._parent_context_resolver = None
    request_resolver._request_resolver = request_resolver
    assert (
        await compiler_module._build_async_slot_impl(workflow=delegated_workflow)(
            request_resolver,
        )
        == "delegated"
    )

    uncached_workflow = _workflow_plan(
        slot=3,
        provider_attribute="instance",
        provides=str,
        requires_async=True,
        is_cached=False,
    )
    runtime_uncached = _runtime(
        scopes=(root_scope,),
        workflows=(uncached_workflow,),
        provider_by_slot={3: "value"},
    )
    root_resolver_type = type(
        "RootResolver",
        (),
        {"_runtime": runtime_uncached, "_class_plan": root_scope},
    )
    root_resolver = root_resolver_type()
    root_resolver._root_resolver = root_resolver
    root_resolver._cleanup_enabled = True
    root_resolver._context = None
    root_resolver._parent_context_resolver = None
    assert (
        await compiler_module._build_async_slot_impl(workflow=uncached_workflow)(root_resolver)
        == "value"
    )


def test_sync_slot_thread_lock_second_cached_branch() -> None:
    root_scope = _scope_plan(level=1, name="app")
    workflow = _workflow_plan(
        slot=1,
        provider_attribute="instance",
        provides=int,
        uses_thread_lock=True,
        is_cached=True,
        cache_owner_scope_level=1,
    )
    runtime = _runtime(
        scopes=(root_scope,),
        workflows=(workflow,),
        provider_by_slot={1: 10},
    )
    resolver_type = type("RootResolver", (), {"_runtime": runtime, "_class_plan": root_scope})
    resolver = resolver_type()
    resolver._root_resolver = resolver
    resolver._cleanup_enabled = True
    resolver._context = None
    resolver._parent_context_resolver = None
    resolver._cache_1 = compiler_module._MISSING_CACHE

    class _HookLock:
        def __enter__(self) -> None:
            resolver._cache_1 = 42

        def __exit__(self, *_args: object) -> None:
            return None

    runtime.thread_lock_by_slot[1] = cast("Any", _HookLock())
    assert compiler_module._build_sync_slot_impl(workflow=workflow)(resolver) == 42


def test_sync_slot_cached_fast_returns_without_lock() -> None:
    root_scope = _scope_plan(level=1, name="app")
    thread_locked = _workflow_plan(
        slot=1,
        provider_attribute="instance",
        provides=int,
        uses_thread_lock=True,
        is_cached=True,
        cache_owner_scope_level=1,
    )
    uncached_lockless = _workflow_plan(
        slot=2,
        provider_attribute="instance",
        provides=int,
        uses_thread_lock=False,
        is_cached=True,
        cache_owner_scope_level=1,
    )
    runtime = _runtime(
        scopes=(root_scope,),
        workflows=(thread_locked, uncached_lockless),
        provider_by_slot={1: 10, 2: 20},
    )
    resolver_type = type("RootResolver", (), {"_runtime": runtime, "_class_plan": root_scope})
    resolver = resolver_type()
    resolver._root_resolver = resolver
    resolver._cleanup_enabled = True
    resolver._context = None
    resolver._parent_context_resolver = None
    resolver._cache_1 = 11
    resolver._cache_2 = 22

    class _NeverEnterLock:
        def __enter__(self) -> None:
            msg = "lock should not be acquired for cached fast path"
            raise AssertionError(msg)

        def __exit__(self, *_args: object) -> None:
            return None

    runtime.thread_lock_by_slot[1] = cast("Any", _NeverEnterLock())
    assert compiler_module._build_sync_slot_impl(workflow=thread_locked)(resolver) == 11
    assert compiler_module._build_sync_slot_impl(workflow=uncached_lockless)(resolver) == 22


@pytest.mark.asyncio
async def test_async_slot_cached_fast_returns_without_lock() -> None:
    root_scope = _scope_plan(level=1, name="app")
    async_locked = _workflow_plan(
        slot=1,
        provider_attribute="instance",
        provides=int,
        requires_async=True,
        uses_async_lock=True,
        is_cached=True,
        cache_owner_scope_level=1,
    )
    uncached_lockless = _workflow_plan(
        slot=2,
        provider_attribute="instance",
        provides=int,
        requires_async=True,
        uses_async_lock=False,
        is_cached=True,
        cache_owner_scope_level=1,
    )
    runtime = _runtime(
        scopes=(root_scope,),
        workflows=(async_locked, uncached_lockless),
        provider_by_slot={1: 10, 2: 20},
    )
    resolver_type = type("RootResolver", (), {"_runtime": runtime, "_class_plan": root_scope})
    resolver = resolver_type()
    resolver._root_resolver = resolver
    resolver._cleanup_enabled = True
    resolver._context = None
    resolver._parent_context_resolver = None
    resolver._cache_1 = 11
    resolver._cache_2 = 22

    class _NeverAsyncLock:
        async def __aenter__(self) -> None:
            msg = "lock should not be acquired for cached fast path"
            raise AssertionError(msg)

        async def __aexit__(self, *_args: object) -> None:
            return None

    runtime.async_lock_by_slot[1] = cast("Any", _NeverAsyncLock())
    assert await compiler_module._build_async_slot_impl(workflow=async_locked)(resolver) == 11
    assert await compiler_module._build_async_slot_impl(workflow=uncached_lockless)(resolver) == 22


@pytest.mark.asyncio
async def test_resolve_dependency_value_async_remaining_branches() -> None:
    dependency = _dependency()
    runtime = _runtime(scopes=(_scope_plan(level=1, name="app"),), workflows=())

    async def _aresolve_1() -> int:
        return 2

    resolver = SimpleNamespace(
        _resolve_from_context=lambda key: {int: 5}[key],
        resolve_1=lambda: 1,
        aresolve_1=_aresolve_1,
    )

    assert (
        await compiler_module._resolve_dependency_value_async(
            runtime=runtime,
            resolver=resolver,
            dependency_plan=ProviderDependencyPlan(
                kind="omit",
                dependency=dependency,
                dependency_index=0,
            ),
        )
        is compiler_module._OMIT_ARGUMENT
    )

    assert (
        await compiler_module._resolve_dependency_value_async(
            runtime=runtime,
            resolver=resolver,
            dependency_plan=ProviderDependencyPlan(
                kind="literal",
                dependency=dependency,
                dependency_index=0,
                literal_expression="None",
            ),
        )
        is None
    )

    handle_sync = await compiler_module._resolve_dependency_value_async(
        runtime=runtime,
        resolver=resolver,
        dependency_plan=ProviderDependencyPlan(
            kind="provider_handle",
            dependency=dependency,
            dependency_index=0,
            provider_inner_slot=1,
            provider_is_async=False,
        ),
    )
    handle_async = await compiler_module._resolve_dependency_value_async(
        runtime=runtime,
        resolver=resolver,
        dependency_plan=ProviderDependencyPlan(
            kind="provider_handle",
            dependency=dependency,
            dependency_index=0,
            provider_inner_slot=1,
            provider_is_async=True,
        ),
    )
    assert handle_sync() == 1
    assert await handle_async() == 2

    runtime.context_key_by_name = {"ctx": int}
    assert (
        await compiler_module._resolve_dependency_value_async(
            runtime=runtime,
            resolver=resolver,
            dependency_plan=ProviderDependencyPlan(
                kind="context",
                dependency=dependency,
                dependency_index=0,
                ctx_key_global_name="ctx",
            ),
        )
        == 5
    )

    runtime.workflows_by_slot = {
        1: _workflow_plan(slot=1, is_cached=False, requires_async=True),
    }
    assert await compiler_module._resolve_dependency_value_async(
        runtime=runtime,
        resolver=resolver,
        dependency_plan=ProviderDependencyPlan(
            kind="all",
            dependency=dependency,
            dependency_index=0,
            all_slots=(1,),
        ),
    ) == (2,)
    assert (
        await compiler_module._resolve_dependency_value_async(
            runtime=runtime,
            resolver=resolver,
            dependency_plan=ProviderDependencyPlan(
                kind="all",
                dependency=dependency,
                dependency_index=0,
                all_slots=(),
            ),
        )
        == ()
    )

    with pytest.raises(ValueError, match="missing dependency slot"):
        await compiler_module._resolve_dependency_value_async(
            runtime=runtime,
            resolver=resolver,
            dependency_plan=ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=0,
                dependency_slot=None,
            ),
        )


def test_dependency_value_for_slot_sync_remaining_branches() -> None:
    root_scope = _scope_plan(level=1, name="app")
    request_scope = _scope_plan(level=3, name="request")
    workflow_root = _workflow_plan(
        slot=1, scope_level=1, is_cached=False, max_required_scope_level=1
    )
    workflow_request = _workflow_plan(slot=2, scope_level=3, is_cached=False)
    runtime = _runtime(
        scopes=(root_scope, request_scope), workflows=(workflow_root, workflow_request)
    )

    root_owner = SimpleNamespace(resolve_1=lambda: "root")
    resolver_type = type("RequestResolver", (), {"_runtime": runtime, "_class_plan": request_scope})
    resolver = resolver_type()
    resolver._root_resolver = root_owner
    resolver.resolve_1 = lambda: "local"
    resolver.resolve_2 = lambda: "async-needed"

    assert (
        compiler_module._dependency_value_for_slot_sync(
            runtime=runtime,
            resolver=resolver,
            dependency_workflow=workflow_root,
        )
        == "root"
    )
    assert (
        compiler_module._dependency_value_for_slot_sync(
            runtime=runtime,
            resolver=resolver,
            dependency_workflow=workflow_request,
        )
        == "async-needed"
    )


def test_argument_part_invalid_name_and_insert_replace_branches() -> None:
    fake_dependency = SimpleNamespace(
        parameter=SimpleNamespace(
            kind=inspect.Parameter.KEYWORD_ONLY,
            name="bad-name",
        ),
    )
    with pytest.raises(ValueError, match="not a valid identifier"):
        compiler_module._argument_part_for_dependency(
            dependency=cast("ProviderDependency", fake_dependency),
            value=1,
            prefer_positional=False,
        )

    parts = [compiler_module._ArgumentPart(kind="starstar", value={"x": 1})]
    compiler_module._insert_internal_resolver_argument(argument_parts=parts, resolver=object())
    assert parts[0].name == "diwire_resolver"

    runtime = _runtime(scopes=(_scope_plan(level=1, name="app"),), workflows=())
    workflow_not_cached = _workflow_plan(slot=9, is_cached=False)
    compiler_module._replace_async_cache(
        runtime=runtime,
        resolver=SimpleNamespace(),
        workflow=workflow_not_cached,
        value=1,
    )


def test_provider_scope_remaining_branches() -> None:
    root_scope = _scope_plan(level=1, name="app")
    request_scope = _scope_plan(level=3, name="request")
    runtime = _runtime(scopes=(root_scope, request_scope), workflows=())

    resolver = SimpleNamespace(
        _root_resolver="root", _request_resolver=compiler_module._MISSING_RESOLVER
    )
    workflow_root_generator = _workflow_plan(slot=1, scope_level=1, provider_attribute="generator")
    assert (
        compiler_module._provider_scope_resolver_for_workflow(
            runtime=runtime,
            resolver=resolver,
            class_scope_level=3,
            workflow=workflow_root_generator,
        )
        == "root"
    )

    workflow_request_generator = _workflow_plan(
        slot=2, scope_level=3, provider_attribute="generator"
    )
    with pytest.raises(DIWireScopeMismatchError):
        compiler_module._provider_scope_resolver_for_workflow(
            runtime=runtime,
            resolver=resolver,
            class_scope_level=4,
            workflow=workflow_request_generator,
        )

    workflow_request_factory = _workflow_plan(slot=3, scope_level=3, provider_attribute="factory")
    with pytest.raises(DIWireScopeMismatchError):
        compiler_module._provider_scope_resolver_for_workflow(
            runtime=runtime,
            resolver=resolver,
            class_scope_level=4,
            workflow=workflow_request_factory,
        )


def test_bootstrap_runtime_handles_annotated_metadata_base_keys() -> None:
    from typing import Annotated

    container = Container()
    key = Annotated[int, "meta"]
    container.add_instance(1, provides=key)
    planner = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )
    plan = planner.build()

    runtime = compiler_module.ResolversAssemblyCompiler()._bootstrap_runtime(
        plan=plan,
        registrations=container._providers_registrations,
        root_scope=Scope.APP,
    )
    slot = container._providers_registrations.get_by_type(int).slot
    assert int in runtime.dep_registered_keys
    assert key not in runtime.dep_registered_keys
    assert runtime.all_slots_by_key[int] == (slot,)


def test_resolver_is_registered_dependency_uses_normalized_fallback() -> None:
    runtime = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(),
    )
    runtime.dep_registered_keys = {int}

    class _Resolver:
        _runtime = runtime

    resolver = _Resolver()

    assert (
        compiler_module._resolver_is_registered_dependency(resolver, Annotated[int, "meta"]) is True
    )


def test_resolver_exit_and_aexit_double_error_branches() -> None:
    def _boom(*_args: Any) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    resolver = SimpleNamespace(
        _cleanup_callbacks=[],
        _owned_scope_resolvers=(SimpleNamespace(__exit__=_boom), SimpleNamespace(__exit__=_boom)),
    )
    with pytest.raises(RuntimeError):
        compiler_module._resolver_exit(resolver, None, None, None)


@pytest.mark.asyncio
async def test_resolver_aexit_double_error_branch() -> None:
    async def _boom(*_args: Any) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    resolver = SimpleNamespace(
        _cleanup_callbacks=[],
        _owned_scope_resolvers=(SimpleNamespace(__aexit__=_boom), SimpleNamespace(__aexit__=_boom)),
    )
    with pytest.raises(RuntimeError):
        await compiler_module._resolver_aexit(resolver, None, None, None)


@pytest.mark.asyncio
async def test_dispatch_fallback_remaining_branches() -> None:
    runtime = SimpleNamespace(all_slots_by_key={})

    class _Resolver:
        _runtime = runtime

        def resolve(self, dependency: Any) -> Any:
            return dependency

        async def aresolve(self, dependency: Any) -> Any:
            return f"a:{dependency}"

        def _is_registered_dependency(self, dependency: Any) -> bool:
            return dependency is int

        def _resolve_from_context(self, key: Any) -> Any:
            return {int: 9}[key]

    resolver = _Resolver()

    maybe_async_provider = compiler_module._resolve_dispatch_fallback_sync(
        resolver,
        Maybe[AsyncProvider[int]],
    )
    assert callable(maybe_async_provider)

    maybe_sync_provider = await compiler_module._resolve_dispatch_fallback_async(
        resolver,
        Maybe[Provider[int]],
    )
    assert callable(maybe_sync_provider)

    assert (
        await compiler_module._resolve_dispatch_fallback_async(resolver, Maybe[int])
        == "a:<class 'int'>"
    )
    assert await compiler_module._resolve_dispatch_fallback_async(resolver, FromContext[int]) == 9
    assert await compiler_module._resolve_dispatch_fallback_async(resolver, All[int]) == ()


@pytest.mark.asyncio
async def test_dispatch_fallback_retries_with_normalized_keys() -> None:
    runtime = SimpleNamespace(all_slots_by_key={int: ()}, dep_registered_keys={int})

    class _Resolver:
        _runtime = runtime

        def resolve(self, dependency: Any) -> Any:
            if dependency is int:
                return 11
            msg = "missing"
            raise DIWireDependencyNotRegisteredError(msg)

        async def aresolve(self, dependency: Any) -> Any:
            if dependency is int:
                return 22
            msg = "missing"
            raise DIWireDependencyNotRegisteredError(msg)

        def _is_registered_dependency(self, dependency: Any) -> bool:
            return compiler_module._resolver_is_registered_dependency(self, dependency)

        def _resolve_from_context(self, key: Any) -> Any:
            return {int: 9}[key]

    resolver = _Resolver()

    assert compiler_module._resolve_dispatch_fallback_sync(resolver, Annotated[int, "meta"]) == 11
    assert (
        await compiler_module._resolve_dispatch_fallback_async(resolver, Annotated[int, "meta"])
        == 22
    )
    assert (
        compiler_module._resolve_dispatch_fallback_sync(
            resolver,
            FromContext[Annotated[int, "meta"]],
        )
        == 9
    )


@pytest.mark.asyncio
async def test_dispatch_fallback_maybe_normalized_retry_paths() -> None:
    class _Resolver:
        def _is_registered_dependency(self, _dependency: Any) -> bool:
            return True

        def resolve(self, dependency: Any) -> Any:
            if dependency is int:
                return 11
            msg = "missing"
            raise DIWireDependencyNotRegisteredError(msg)

        async def aresolve(self, dependency: Any) -> Any:
            if dependency is int:
                return 22
            msg = "missing"
            raise DIWireDependencyNotRegisteredError(msg)

    resolver = _Resolver()

    assert (
        compiler_module._resolve_dispatch_fallback_sync(
            resolver,
            Maybe[Annotated[int, "meta"]],
        )
        == 11
    )
    assert (
        await compiler_module._resolve_dispatch_fallback_async(
            resolver,
            Maybe[Annotated[int, "meta"]],
        )
        == 22
    )


@pytest.mark.asyncio
async def test_dispatch_fallback_maybe_normalized_retry_returns_none_on_second_miss() -> None:
    class _Resolver:
        def _is_registered_dependency(self, _dependency: Any) -> bool:
            return True

        def resolve(self, _dependency: Any) -> Any:
            msg = "missing"
            raise DIWireDependencyNotRegisteredError(msg)

        async def aresolve(self, _dependency: Any) -> Any:
            msg = "missing"
            raise DIWireDependencyNotRegisteredError(msg)

    resolver = _Resolver()

    assert (
        compiler_module._resolve_dispatch_fallback_sync(
            resolver,
            Maybe[Annotated[int, "meta"]],
        )
        is None
    )
    assert compiler_module._resolve_dispatch_fallback_sync(resolver, Maybe[str]) is None
    assert (
        await compiler_module._resolve_dispatch_fallback_async(
            resolver,
            Maybe[Annotated[int, "meta"]],
        )
        is None
    )
    assert await compiler_module._resolve_dispatch_fallback_async(resolver, Maybe[str]) is None


@pytest.mark.asyncio
async def test_dispatch_fallback_async_normalized_retry_missing_raises_error() -> None:
    class _Resolver:
        async def aresolve(self, _dependency: Any) -> Any:
            msg = "missing"
            raise DIWireDependencyNotRegisteredError(msg)

    resolver = _Resolver()

    with pytest.raises(DIWireDependencyNotRegisteredError):
        await compiler_module._resolve_dispatch_fallback_async(resolver, Annotated[int, "meta"])


def test_build_argument_parts_omit_branches_sync_and_async() -> None:
    dependency_a = _dependency(name="a", kind=inspect.Parameter.POSITIONAL_ONLY)
    dependency_b = _dependency(name="b", kind=inspect.Parameter.POSITIONAL_ONLY)
    workflow = _workflow_plan(
        slot=1,
        dependencies=(dependency_a, dependency_b),
        dependency_slots=(None, None),
        dependency_requires_async=(False, False),
        dependency_plans=(
            ProviderDependencyPlan(
                kind="omit",
                dependency=dependency_a,
                dependency_index=0,
            ),
            ProviderDependencyPlan(
                kind="provider",
                dependency=dependency_b,
                dependency_index=1,
                dependency_slot=1,
            ),
        ),
    )
    runtime = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(workflow,),
    )
    resolver = SimpleNamespace(resolve_1=lambda: 1)
    assert (
        compiler_module._build_argument_parts_sync(
            runtime=runtime,
            resolver=resolver,
            workflow=workflow,
        )
        == []
    )

    async def _aresolve_1() -> int:
        return 1

    resolver_async = SimpleNamespace(resolve_1=lambda: 1, aresolve_1=_aresolve_1)
    assert (
        asyncio.run(
            cast(
                "Any",
                compiler_module._build_argument_parts_async(
                    runtime=runtime,
                    resolver=resolver_async,
                    workflow=workflow,
                ),
            ),
        )
        == []
    )


@pytest.mark.asyncio
async def test_resolve_dependency_value_async_missing_context_key_error() -> None:
    with pytest.raises(ValueError, match="context key global name"):
        await compiler_module._resolve_dependency_value_async(
            runtime=_runtime(scopes=(_scope_plan(level=1, name="app"),), workflows=()),
            resolver=SimpleNamespace(),
            dependency_plan=ProviderDependencyPlan(
                kind="context",
                dependency=_dependency(),
                dependency_index=0,
                ctx_key_global_name=None,
            ),
        )


def test_dependency_value_for_slot_sync_fallthrough_return() -> None:
    root_scope = _scope_plan(level=1, name="app")
    workflow = _workflow_plan(slot=1, scope_level=1, is_cached=False)
    runtime = _runtime(scopes=(root_scope,), workflows=(workflow,))
    resolver_type = type("RootResolver", (), {"_runtime": runtime, "_class_plan": root_scope})
    resolver = resolver_type()
    resolver.resolve_1 = lambda: "fallthrough"
    assert (
        compiler_module._dependency_value_for_slot_sync(
            runtime=runtime,
            resolver=resolver,
            dependency_workflow=workflow,
        )
        == "fallthrough"
    )


@pytest.mark.asyncio
async def test_build_local_value_async_sync_generator_cleanup_enabled_branch() -> None:
    events: list[str] = []

    def _provider() -> Any:
        events.append("enter")
        yield 3

    workflow = _workflow_plan(
        slot=11,
        provider_attribute="generator",
        is_provider_async=False,
        is_cached=False,
    )
    runtime = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(workflow,),
        provider_by_slot={11: _provider},
    )
    scope_resolver = SimpleNamespace(_cleanup_callbacks=[])
    value = await compiler_module._build_local_value_async(
        runtime=runtime,
        resolver=SimpleNamespace(_cleanup_enabled=True),
        workflow=workflow,
        provider_scope_resolver=scope_resolver,
    )
    assert value == 3
    assert scope_resolver._cleanup_callbacks


@pytest.mark.asyncio
async def test_build_local_value_async_sync_context_manager_cleanup_disabled_branch() -> None:
    class _SyncCM:
        def __enter__(self) -> int:
            return 4

        def __exit__(self, *_args: object) -> None:
            return None

    workflow = _workflow_plan(
        slot=12,
        provider_attribute="context_manager",
        is_provider_async=False,
        is_cached=False,
    )
    runtime = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(workflow,),
        provider_by_slot={12: _SyncCM},
    )
    scope_resolver = SimpleNamespace(_cleanup_callbacks=[])
    value = await compiler_module._build_local_value_async(
        runtime=runtime,
        resolver=SimpleNamespace(_cleanup_enabled=False),
        workflow=workflow,
        provider_scope_resolver=scope_resolver,
    )
    assert value == 4
    assert scope_resolver._cleanup_callbacks == []


def test_provider_scope_non_root_available_branch() -> None:
    root_scope = _scope_plan(level=1, name="app")
    request_scope = _scope_plan(level=3, name="request")
    runtime = _runtime(scopes=(root_scope, request_scope), workflows=())
    resolver = SimpleNamespace(_request_resolver="request", _root_resolver="root")
    workflow = _workflow_plan(slot=13, scope_level=3, provider_attribute="generator")
    assert (
        compiler_module._provider_scope_resolver_for_workflow(
            runtime=runtime,
            resolver=resolver,
            class_scope_level=4,
            workflow=workflow,
        )
        == "request"
    )


def test_build_argument_parts_omit_keyword_only_branch_paths() -> None:
    dependency = _dependency(name="value", kind=inspect.Parameter.KEYWORD_ONLY)
    workflow = _workflow_plan(
        slot=21,
        dependencies=(dependency,),
        dependency_slots=(None,),
        dependency_requires_async=(False,),
        dependency_plans=(
            ProviderDependencyPlan(
                kind="omit",
                dependency=dependency,
                dependency_index=0,
            ),
        ),
    )
    runtime = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(workflow,),
    )
    resolver = SimpleNamespace()
    assert (
        compiler_module._build_argument_parts_sync(
            runtime=runtime,
            resolver=resolver,
            workflow=workflow,
        )
        == []
    )

    assert (
        asyncio.run(
            cast(
                "Any",
                compiler_module._build_argument_parts_async(
                    runtime=runtime,
                    resolver=resolver,
                    workflow=workflow,
                ),
            ),
        )
        == []
    )


def test_optimized_sync_dependency_expression_additional_branches() -> None:
    compiler = compiler_module.ResolversAssemblyCompiler()
    root_scope = _scope_plan(level=1, name="app")
    request_scope = _scope_plan(level=3, name="request")
    action_scope = _scope_plan(level=4, name="action")
    workflow_root = _workflow_plan(
        slot=1,
        scope_level=1,
        is_cached=False,
        provider_attribute="factory",
        max_required_scope_level=1,
    )
    workflow_request = _workflow_plan(
        slot=2,
        scope_level=3,
        is_cached=False,
        max_required_scope_level=3,
    )
    runtime = _runtime(
        scopes=(root_scope, request_scope, action_scope),
        workflows=(workflow_root, workflow_request),
    )

    dependency = _dependency()
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=action_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="omit",
                dependency=dependency,
                dependency_index=0,
            ),
            resolver_expression="self",
        )
        is None
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=action_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="literal",
                dependency=dependency,
                dependency_index=0,
                literal_expression="None",
            ),
            resolver_expression="self",
        )
        == "None"
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=action_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="provider_handle",
                dependency=dependency,
                dependency_index=0,
                provider_inner_slot=None,
            ),
            resolver_expression="self",
        )
        is compiler_module._FALLBACK_ARGUMENT_EXPRESSION
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=action_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="context",
                dependency=dependency,
                dependency_index=0,
                ctx_key_global_name=None,
            ),
            resolver_expression="self",
        )
        is compiler_module._FALLBACK_ARGUMENT_EXPRESSION
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=action_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="all",
                dependency=dependency,
                dependency_index=0,
                all_slots=(),
            ),
            resolver_expression="self",
        )
        == "()"
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=action_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="all",
                dependency=dependency,
                dependency_index=0,
                all_slots=(1,),
            ),
            resolver_expression="self",
        )
        == "(self.resolve_1(),)"
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=action_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="all",
                dependency=dependency,
                dependency_index=0,
                all_slots=(1, 2),
            ),
            resolver_expression="self",
        )
        == "(self.resolve_1(), self.resolve_2())"
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=action_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=0,
                dependency_slot=None,
            ),
            resolver_expression="self",
        )
        is compiler_module._FALLBACK_ARGUMENT_EXPRESSION
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=action_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=0,
                dependency_slot=1,
            ),
            resolver_expression="self",
        )
        == "self._root_resolver.resolve_1()"
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=action_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=0,
                dependency_slot=2,
            ),
            resolver_expression="self",
        )
        == "self._request_resolver.resolve_2()"
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=root_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=0,
                dependency_slot=1,
            ),
            resolver_expression="self",
        )
        == "_provider_1()"
    )


def test_resolver_init_additional_branches() -> None:
    root_scope = _scope_plan(level=1, name="app")
    request_scope = _scope_plan(level=3, name="request")
    tenant_scope = _scope_plan(level=2, name="tenant")
    session_scope = _scope_plan(level=4, name="session")

    workflow_root_cache = _workflow_plan(
        slot=70,
        scope_level=1,
        is_cached=True,
        cache_owner_scope_level=1,
    )
    root_runtime = _runtime(
        scopes=(root_scope, request_scope),
        workflows=(workflow_root_cache,),
        uses_stateless_scope_reuse=True,
    )

    class _ScopeCtor:
        def __init__(self, *args: Any) -> None:
            self.args = args
            self._active = True

    root_runtime.class_by_level = {3: _ScopeCtor}

    class _RootResolver:
        _runtime = root_runtime
        _class_plan = root_scope
        _last_sync_dependency = compiler_module._MISSING_DEP_SLOT
        _last_sync_method: Any | None = None
        _last_async_dependency = compiler_module._MISSING_DEP_SLOT
        _last_async_method: Any | None = None

    root_resolver = _RootResolver()
    root_resolver_any = cast("Any", root_resolver)
    compiler_module._resolver_init(
        root_resolver,
        root_resolver=None,
        cleanup_enabled=True,
        context=None,
        parent_context_resolver=None,
    )
    assert root_resolver_any._root_resolver is root_resolver
    assert root_resolver_any._cache_70 is compiler_module._MISSING_CACHE
    assert root_resolver_any._last_sync_dependency is compiler_module._MISSING_DEP_SLOT
    assert root_resolver_any._last_sync_method is None
    assert root_resolver_any._last_async_dependency is compiler_module._MISSING_DEP_SLOT
    assert root_resolver_any._last_async_method is None
    assert root_resolver_any._cleanup_callbacks == []
    assert root_resolver_any._scope_resolver_3._active is False

    no_cleanup_runtime = _runtime(
        scopes=(root_scope, request_scope),
        workflows=(),
        uses_stateless_scope_reuse=False,
    )
    no_cleanup_runtime.has_cleanup = False
    no_cleanup_runtime.class_by_level = {3: _ScopeCtor}

    class _RootNoCleanupResolver:
        _runtime = no_cleanup_runtime
        _class_plan = root_scope

    no_cleanup_resolver = _RootNoCleanupResolver()
    no_cleanup_resolver_any = cast("Any", no_cleanup_resolver)
    compiler_module._resolver_init(
        no_cleanup_resolver,
        root_resolver=None,
        cleanup_enabled=False,
        context=None,
        parent_context_resolver=None,
    )
    assert no_cleanup_resolver_any._scope_resolver_3.args[0] is no_cleanup_resolver

    workflow_request_cache = _workflow_plan(
        slot=71,
        scope_level=3,
        is_cached=True,
        cache_owner_scope_level=3,
    )
    non_root_runtime = _runtime(
        scopes=(root_scope, tenant_scope, request_scope, session_scope),
        workflows=(workflow_request_cache,),
    )

    class _RequestResolver:
        _runtime = non_root_runtime
        _class_plan = request_scope

    parent_tenant_type = type(
        "TenantResolver",
        (),
        {"_class_plan": tenant_scope},
    )
    parent_tenant = parent_tenant_type()

    request_resolver = _RequestResolver()
    request_resolver_any = cast("Any", request_resolver)
    compiler_module._resolver_init(
        request_resolver,
        root_resolver="root",
        cleanup_enabled=True,
        context={"k": "v"},
        parent_context_resolver=parent_tenant,
    )
    assert request_resolver_any._root_resolver == "root"
    assert request_resolver_any._request_resolver is request_resolver
    assert request_resolver_any._tenant_resolver is parent_tenant
    assert request_resolver_any._cache_71 is compiler_module._MISSING_CACHE

    parent_session_type = type(
        "SessionResolver",
        (),
        {"_class_plan": session_scope, "_tenant_resolver": "tenant-owner"},
    )
    parent_session = parent_session_type()

    request_resolver_2 = _RequestResolver()
    request_resolver_2_any = cast("Any", request_resolver_2)
    compiler_module._resolver_init(
        request_resolver_2,
        root_resolver="root",
        cleanup_enabled=True,
        context=None,
        parent_context_resolver=parent_session,
    )
    assert request_resolver_2_any._tenant_resolver == "tenant-owner"

    request_resolver_3 = _RequestResolver()
    request_resolver_3_any = cast("Any", request_resolver_3)
    compiler_module._resolver_init(
        request_resolver_3,
        root_resolver="root",
        cleanup_enabled=True,
        context=None,
        parent_context_resolver=None,
    )
    assert request_resolver_3_any._tenant_resolver is compiler_module._MISSING_RESOLVER


def test_resolver_enter_scope_and_transition_additional_branches() -> None:
    root_scope = _scope_plan(level=1, name="app")
    request_scope = _scope_plan(level=3, name="request")
    session_scope = _scope_plan(level=4, name="session")

    runtime = _runtime(
        scopes=(root_scope, request_scope, session_scope),
        workflows=(),
        uses_stateless_scope_reuse=False,
    )

    class _Ctor:
        def __init__(self, *args: Any) -> None:
            self.args = args

    runtime.class_by_level = {3: _Ctor, 4: _Ctor}

    root_type = type("RootResolver", (), {"_runtime": runtime, "_class_plan": root_scope})
    root_resolver = root_type()
    root_resolver._root_resolver = root_resolver
    root_resolver._context = None
    root_resolver._parent_context_resolver = None
    root_resolver._cleanup_enabled = True

    assert isinstance(compiler_module._resolver_enter_scope(root_resolver, None, None), _Ctor)
    assert isinstance(compiler_module._resolver_enter_scope(root_resolver, 3, None), _Ctor)

    stateless_runtime = _runtime(
        scopes=(root_scope, request_scope, session_scope),
        workflows=(),
        uses_stateless_scope_reuse=True,
    )
    stateless_runtime.class_by_level = {3: _Ctor, 4: _Ctor}
    stateless_root_type = type(
        "StatelessRootResolver",
        (),
        {"_runtime": stateless_runtime, "_class_plan": root_scope},
    )
    stateless_root = stateless_root_type()
    stateless_root._root_resolver = stateless_root
    stateless_root._context = None
    stateless_root._parent_context_resolver = None
    stateless_root._cleanup_enabled = True
    stateless_root._scope_resolver_3 = "pooled-request"

    created = compiler_module._resolver_enter_scope(stateless_root, 4, {"ctx": 1})
    assert isinstance(created, _Ctor)
    assert created.args[0] is stateless_root

    assert (
        compiler_module._instantiate_scope_transition(
            runtime=stateless_runtime,
            current_resolver=stateless_root,
            target_scope=request_scope,
            context=None,
        )
        == "pooled-request"
    )


def test_sync_slot_impl_delegation_and_async_required_branches() -> None:
    root_scope = _scope_plan(level=1, name="app")
    request_scope = _scope_plan(level=3, name="request")

    delegated_workflow = _workflow_plan(
        slot=61,
        scope_level=1,
        max_required_scope_level=1,
        is_cached=False,
        requires_async=False,
    )
    delegated_runtime = _runtime(
        scopes=(root_scope, request_scope),
        workflows=(delegated_workflow,),
        provider_by_slot={61: object()},
    )

    delegated_type = type(
        "DelegatedResolver",
        (),
        {"_runtime": delegated_runtime, "_class_plan": request_scope},
    )
    delegated_resolver = delegated_type()
    delegated_resolver._root_resolver = SimpleNamespace(resolve_61=lambda: "delegated")
    delegated_resolver._request_resolver = delegated_resolver
    delegated_resolver._cleanup_enabled = True
    delegated_resolver._context = None
    delegated_resolver._parent_context_resolver = None
    assert compiler_module._build_sync_slot_impl(workflow=delegated_workflow)(
        delegated_resolver
    ) == ("delegated")

    async_workflow = _workflow_plan(
        slot=62,
        scope_level=3,
        max_required_scope_level=3,
        is_cached=False,
        requires_async=True,
    )
    async_runtime = _runtime(
        scopes=(root_scope, request_scope),
        workflows=(async_workflow,),
        provider_by_slot={62: object()},
    )
    async_type = type(
        "AsyncRequiredResolver",
        (),
        {"_runtime": async_runtime, "_class_plan": request_scope},
    )
    async_resolver = async_type()
    async_resolver._root_resolver = async_resolver
    async_resolver._request_resolver = async_resolver
    async_resolver._cleanup_enabled = True
    async_resolver._context = None
    async_resolver._parent_context_resolver = None
    with pytest.raises(DIWireAsyncDependencyInSyncContextError):
        compiler_module._build_sync_slot_impl(workflow=async_workflow)(async_resolver)


def test_build_local_value_sync_argumented_branches() -> None:
    dependency = _dependency(name="value")
    dependency_plan = ProviderDependencyPlan(
        kind="literal",
        dependency=dependency,
        dependency_index=0,
        literal_expression="None",
    )

    class _SyncCM:
        def __enter__(self) -> int:
            return 23

        def __exit__(self, *_args: object) -> None:
            return None

    def _generator(_value: Any = None) -> Any:
        yield 11

    workflows = (
        _workflow_plan(
            slot=30,
            provider_attribute="instance",
            is_cached=False,
            dependencies=(dependency,),
            dependency_plans=(dependency_plan,),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
        ),
        _workflow_plan(
            slot=31,
            provider_attribute="factory",
            is_provider_async=True,
            is_cached=False,
            dependencies=(dependency,),
            dependency_plans=(dependency_plan,),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
        ),
        _workflow_plan(
            slot=32,
            provider_attribute="generator",
            is_cached=False,
            dependencies=(dependency,),
            dependency_plans=(dependency_plan,),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
        ),
        _workflow_plan(
            slot=33,
            provider_attribute="context_manager",
            is_provider_async=True,
            is_cached=False,
            dependencies=(dependency,),
            dependency_plans=(dependency_plan,),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
        ),
        _workflow_plan(
            slot=34,
            provider_attribute="context_manager",
            is_provider_async=False,
            is_cached=False,
            dependencies=(dependency,),
            dependency_plans=(dependency_plan,),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
        ),
        _workflow_plan(
            slot=35,
            provider_attribute="unsupported",
            is_cached=False,
            dependencies=(dependency,),
            dependency_plans=(dependency_plan,),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
        ),
        _workflow_plan(
            slot=36,
            provider_attribute="generator",
            is_provider_async=True,
            is_cached=False,
            dependencies=(dependency,),
            dependency_plans=(dependency_plan,),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
        ),
    )
    runtime = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=workflows,
        provider_by_slot={
            30: "instance",
            31: lambda _value=None: 17,
            32: _generator,
            33: lambda _value=None: object(),
            34: lambda _value=None: _SyncCM(),
            35: lambda _value=None: object(),
            36: _generator,
        },
    )

    cleanup_scope = SimpleNamespace(_cleanup_callbacks=[])
    resolver_cleanup = SimpleNamespace(_cleanup_enabled=True)
    resolver_no_cleanup = SimpleNamespace(_cleanup_enabled=False)

    assert (
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[0],
            provider_scope_resolver=cleanup_scope,
        )
        == "instance"
    )
    assert (
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[1],
            provider_scope_resolver=cleanup_scope,
        )
        == 17
    )
    assert (
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[2],
            provider_scope_resolver=cleanup_scope,
        )
        == 11
    )
    assert cleanup_scope._cleanup_callbacks
    assert (
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver_no_cleanup,
            workflow=workflows[2],
            provider_scope_resolver=cleanup_scope,
        )
        == 11
    )
    with pytest.raises(DIWireScopeMismatchError):
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[2],
            provider_scope_resolver=compiler_module._MISSING_RESOLVER,
        )
    with pytest.raises(DIWireAsyncDependencyInSyncContextError):
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[6],
            provider_scope_resolver=cleanup_scope,
        )

    with pytest.raises(DIWireScopeMismatchError):
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[4],
            provider_scope_resolver=compiler_module._MISSING_RESOLVER,
        )
    with pytest.raises(DIWireAsyncDependencyInSyncContextError):
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[3],
            provider_scope_resolver=cleanup_scope,
        )
    assert (
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[4],
            provider_scope_resolver=cleanup_scope,
        )
        == 23
    )
    assert (
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver_no_cleanup,
            workflow=workflows[4],
            provider_scope_resolver=cleanup_scope,
        )
        == 23
    )
    with pytest.raises(ValueError, match="Unsupported provider attribute"):
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[5],
            provider_scope_resolver=cleanup_scope,
        )


@pytest.mark.asyncio
async def test_build_local_value_async_argumented_branches() -> None:
    dependency = _dependency(name="value")
    dependency_plan = ProviderDependencyPlan(
        kind="literal",
        dependency=dependency,
        dependency_index=0,
        literal_expression="None",
    )

    async def _async_generator(_value: Any = None) -> Any:
        yield 31

    def _sync_generator(_value: Any = None) -> Any:
        yield 32

    @asynccontextmanager
    async def _async_cm(_value: Any = None) -> Any:
        yield 33

    class _SyncCM:
        def __enter__(self) -> int:
            return 34

        def __exit__(self, *_args: object) -> None:
            return None

    workflows = (
        _workflow_plan(
            slot=40,
            provider_attribute="generator",
            is_provider_async=True,
            is_cached=False,
            dependencies=(dependency,),
            dependency_plans=(dependency_plan,),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
        ),
        _workflow_plan(
            slot=41,
            provider_attribute="generator",
            is_provider_async=False,
            is_cached=False,
            dependencies=(dependency,),
            dependency_plans=(dependency_plan,),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
        ),
        _workflow_plan(
            slot=42,
            provider_attribute="context_manager",
            is_provider_async=True,
            is_cached=False,
            dependencies=(dependency,),
            dependency_plans=(dependency_plan,),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
        ),
        _workflow_plan(
            slot=43,
            provider_attribute="context_manager",
            is_provider_async=False,
            is_cached=False,
            dependencies=(dependency,),
            dependency_plans=(dependency_plan,),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
        ),
        _workflow_plan(
            slot=44,
            provider_attribute="unsupported",
            is_cached=False,
            dependencies=(dependency,),
            dependency_plans=(dependency_plan,),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
        ),
    )
    runtime = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=workflows,
        provider_by_slot={
            40: _async_generator,
            41: _sync_generator,
            42: lambda _value=None: _async_cm(),
            43: lambda _value=None: _SyncCM(),
            44: lambda _value=None: object(),
        },
    )

    cleanup_scope = SimpleNamespace(_cleanup_callbacks=[])
    resolver_cleanup = SimpleNamespace(_cleanup_enabled=True)
    resolver_no_cleanup = SimpleNamespace(_cleanup_enabled=False)

    with pytest.raises(DIWireScopeMismatchError):
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[0],
            provider_scope_resolver=compiler_module._MISSING_RESOLVER,
        )
    assert (
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[0],
            provider_scope_resolver=cleanup_scope,
        )
        == 31
    )
    assert cleanup_scope._cleanup_callbacks
    assert (
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver_no_cleanup,
            workflow=workflows[0],
            provider_scope_resolver=cleanup_scope,
        )
        == 31
    )
    assert (
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[1],
            provider_scope_resolver=cleanup_scope,
        )
        == 32
    )
    assert (
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver_no_cleanup,
            workflow=workflows[1],
            provider_scope_resolver=cleanup_scope,
        )
        == 32
    )
    with pytest.raises(DIWireScopeMismatchError):
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[2],
            provider_scope_resolver=compiler_module._MISSING_RESOLVER,
        )
    assert (
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[2],
            provider_scope_resolver=cleanup_scope,
        )
        == 33
    )
    assert (
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver_no_cleanup,
            workflow=workflows[2],
            provider_scope_resolver=cleanup_scope,
        )
        == 33
    )
    assert (
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[3],
            provider_scope_resolver=cleanup_scope,
        )
        == 34
    )
    assert (
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver_no_cleanup,
            workflow=workflows[3],
            provider_scope_resolver=cleanup_scope,
        )
        == 34
    )
    with pytest.raises(ValueError, match="Unsupported provider attribute"):
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver_cleanup,
            workflow=workflows[4],
            provider_scope_resolver=cleanup_scope,
        )


@pytest.mark.asyncio
async def test_build_local_value_async_no_arguments_sync_factory_branch() -> None:
    workflow = _workflow_plan(
        slot=80,
        provider_attribute="factory",
        is_provider_async=False,
        is_cached=False,
    )
    assert (
        await compiler_module._build_local_value_async_no_arguments(
            resolver=SimpleNamespace(_cleanup_enabled=False),
            workflow=workflow,
            provider_scope_resolver=SimpleNamespace(_cleanup_callbacks=[]),
            provider=lambda: 123,
        )
        == 123
    )


def test_build_argument_parts_fallback_and_empty_branches() -> None:
    dependency = _dependency(name="value")
    dep_workflow_sync = _workflow_plan(slot=1, is_cached=False, scope_level=1)
    fallback_workflow_sync = _workflow_plan(
        slot=50,
        is_cached=False,
        dependencies=(dependency,),
        dependency_slots=(1,),
        dependency_requires_async=(False,),
        dependency_plans=(),
    )
    empty_workflow_sync = _workflow_plan(
        slot=51,
        is_cached=False,
        dependencies=(),
        dependency_slots=(),
        dependency_requires_async=(),
        dependency_plans=(),
        provider_is_inject_wrapper=False,
    )
    runtime_sync = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(dep_workflow_sync, fallback_workflow_sync, empty_workflow_sync),
    )
    sync_resolver_type = type(
        "SyncResolver",
        (),
        {"_class_plan": SimpleNamespace(scope_level=1)},
    )
    resolver_sync = sync_resolver_type()
    resolver_sync.resolve_1 = lambda: 5
    parts_sync = compiler_module._build_argument_parts_sync(
        runtime=runtime_sync,
        resolver=resolver_sync,
        workflow=fallback_workflow_sync,
    )
    assert parts_sync
    assert parts_sync[0].value == 5
    assert (
        compiler_module._build_argument_parts_sync(
            runtime=runtime_sync,
            resolver=resolver_sync,
            workflow=empty_workflow_sync,
        )
        == []
    )

    dep_workflow_async = _workflow_plan(
        slot=2,
        is_cached=False,
        scope_level=1,
        requires_async=True,
    )
    fallback_workflow_async = _workflow_plan(
        slot=52,
        is_cached=False,
        dependencies=(dependency,),
        dependency_slots=(2,),
        dependency_requires_async=(True,),
        dependency_plans=(),
        requires_async=True,
    )
    empty_workflow_async = _workflow_plan(
        slot=53,
        is_cached=False,
        dependencies=(),
        dependency_slots=(),
        dependency_requires_async=(),
        dependency_plans=(),
        provider_is_inject_wrapper=False,
    )
    runtime_async = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(dep_workflow_async, fallback_workflow_async, empty_workflow_async),
    )

    async def _aresolve_2() -> int:
        return 6

    async_resolver_type = type(
        "AsyncResolver",
        (),
        {"_class_plan": SimpleNamespace(scope_level=1)},
    )
    resolver_async = async_resolver_type()
    resolver_async.resolve_2 = lambda: 0
    resolver_async.aresolve_2 = _aresolve_2
    parts_async = asyncio.run(
        cast(
            "Any",
            compiler_module._build_argument_parts_async(
                runtime=runtime_async,
                resolver=resolver_async,
                workflow=fallback_workflow_async,
            ),
        ),
    )
    assert parts_async
    assert parts_async[0].value == 6
    assert (
        asyncio.run(
            cast(
                "Any",
                compiler_module._build_argument_parts_async(
                    runtime=runtime_async,
                    resolver=resolver_async,
                    workflow=empty_workflow_async,
                ),
            ),
        )
        == []
    )


def test_resolve_dependency_value_sync_async_provider_handle_branch() -> None:
    runtime = _runtime(scopes=(_scope_plan(level=1, name="app"),), workflows=())

    async def _aresolve_1() -> int:
        return 77

    resolver = SimpleNamespace(aresolve_1=_aresolve_1, resolve_1=lambda: 1)
    handle = compiler_module._resolve_dependency_value_sync(
        runtime=runtime,
        resolver=resolver,
        dependency_plan=ProviderDependencyPlan(
            kind="provider_handle",
            dependency=_dependency(),
            dependency_index=0,
            provider_inner_slot=1,
            provider_is_async=True,
        ),
    )
    assert asyncio.run(cast("Any", handle)()) == 77


def test_resolver_scope_level_branch() -> None:
    resolver_type = type("ScopedResolver", (), {"_class_plan": SimpleNamespace(scope_level=9)})
    assert compiler_module._resolver_scope_level(resolver_type()) == 9
