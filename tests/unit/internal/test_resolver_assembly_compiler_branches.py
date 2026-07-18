from __future__ import annotations

import ast
import asyncio
import dis
import inspect
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Annotated, Any, cast

import pytest

from diwire import All, AsyncProvider, Container, Lifetime, Maybe, Provider, Scope
from diwire._internal.lock_mode import LockMode
from diwire._internal.providers import MaterializedProviderCallPlan, ProviderDependency
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
        thread_lock_by_slot={
            workflow.slot: threading.Lock() for workflow in workflows if workflow.uses_thread_lock
        },
        async_lock_by_slot={
            workflow.slot: asyncio.Lock() for workflow in workflows if workflow.uses_async_lock
        },
        cache_slots_by_owner_level=cache_slots_by_owner_level,
        next_scope_options_by_level=next_scope_options_by_level,
    )


def _eligible_materialized_workflow() -> tuple[
    ProviderWorkflowPlan,
    MaterializedProviderCallPlan,
]:
    call_plan = MaterializedProviderCallPlan(
        provider=lambda argument: argument,
        argument=int,
    )
    workflow = replace(
        _workflow_plan(
            slot=1,
            provider_attribute="factory",
            is_cached=False,
            cache_owner_scope_level=None,
        ),
        lock_mode=LockMode.NONE,
        effective_lock_mode=LockMode.NONE,
        needs_cleanup=False,
        materialized_call_plan=call_plan,
    )
    return workflow, call_plan


def test_sync_materialized_provider_call_plan_accepts_exact_safe_shape() -> None:
    workflow, call_plan = _eligible_materialized_workflow()

    assert compiler_module._sync_materialized_provider_call_plan(workflow) is call_plan


@pytest.mark.parametrize(
    "replacement",
    [
        {"materialized_call_plan": None},
        {"provider_attribute": "concrete_type"},
        {"dependencies": (_dependency(),)},
        {
            "dependency_plans": (
                ProviderDependencyPlan(
                    kind="literal",
                    dependency=_dependency(),
                    dependency_index=0,
                    literal_expression="1",
                ),
            ),
        },
        {"sync_arguments": ("1",)},
        {"effective_lock_mode": LockMode.THREAD},
        {"uses_thread_lock": True},
        {"uses_async_lock": True},
        {"requires_async": True},
        {"is_provider_async": True},
        {"provider_is_inject_wrapper": True},
        {"needs_cleanup": True},
    ],
    ids=(
        "missing-plan",
        "non-factory",
        "dependencies",
        "dependency-plans",
        "sync-arguments",
        "lock-mode",
        "thread-lock",
        "async-lock",
        "requires-async",
        "async-provider",
        "inject-wrapper",
        "cleanup",
    ),
)
def test_sync_materialized_provider_call_plan_rejects_unsafe_workflow(
    replacement: dict[str, Any],
) -> None:
    workflow, _ = _eligible_materialized_workflow()

    assert (
        compiler_module._sync_materialized_provider_call_plan(
            replace(workflow, **replacement),
        )
        is None
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
    container = Container(use_resolver_context=False)

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

    deep = root.enter_scope(Scope.STEP)
    assert deep._owned_scope_resolvers


def test_compiler_stateless_scope_reuse_branches() -> None:
    container = Container(use_resolver_context=False)
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

    explicit = root.enter_scope(Scope.REQUEST)
    assert explicit is root._scope_resolver_3


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

    resolver = _Resolver()

    sync_provider = compiler_module._resolve_dispatch_fallback_sync(resolver, Provider[int])
    assert callable(sync_provider)

    async_provider = await compiler_module._resolve_dispatch_fallback_async(
        resolver,
        Maybe[AsyncProvider[int]],
    )
    assert callable(async_provider)

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
    assert plans[1].kind == "provider"

    assert compiler_module._unique_ordered(["a", "a", "b"]) == ["a", "b"]


def test_bootstrap_runtime_omits_context_key_mapping_state() -> None:
    container = Container()
    container.add_instance(1, provides=int)
    registrations = container._providers_registrations
    compiler = compiler_module.ResolversAssemblyCompiler()
    slot = registrations.get_by_type(int).slot

    workflow = _workflow_plan(
        slot=slot,
        provides=int,
        dependency_plans=(),
    )
    plan = _generation_plan(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(workflow,),
    )

    runtime = compiler._bootstrap_runtime(
        plan=plan, registrations=registrations, root_scope=Scope.APP
    )
    assert runtime.dep_type_by_slot[slot] is int
    assert not hasattr(runtime, "context_key_by_name")


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

    resolver = _Resolver()

    assert compiler_module._resolve_dispatch_fallback_sync(resolver, Annotated[int, "meta"]) == 11
    assert (
        await compiler_module._resolve_dispatch_fallback_async(resolver, Annotated[int, "meta"])
        == 22
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
    workflow_root_cached = _workflow_plan(
        slot=3,
        scope_level=1,
        is_cached=True,
        cache_owner_scope_level=1,
        max_required_scope_level=1,
    )
    workflow_request_cached = _workflow_plan(
        slot=4,
        scope_level=3,
        is_cached=True,
        cache_owner_scope_level=3,
        max_required_scope_level=3,
    )
    workflow_request_async_cached = _workflow_plan(
        slot=5,
        scope_level=3,
        is_cached=True,
        cache_owner_scope_level=3,
        requires_async=True,
        max_required_scope_level=3,
    )
    runtime = _runtime(
        scopes=(root_scope, request_scope, action_scope),
        workflows=(
            workflow_root,
            workflow_request,
            workflow_root_cached,
            workflow_request_cached,
            workflow_request_async_cached,
        ),
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
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=action_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=0,
                dependency_slot=3,
            ),
            resolver_expression="self._root_resolver",
        )
        == "(self._root_resolver._cache_3 if self._root_resolver._cache_3 "
        "is not _MISSING_CACHE else self._root_resolver.resolve_3())"
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=request_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=0,
                dependency_slot=4,
            ),
            resolver_expression="self._root_resolver",
        )
        == "(_cached_dependency_4 if (_cached_dependency_4 := self._cache_4) "
        "is not _MISSING_CACHE else self.resolve_4())"
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=action_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=0,
                dependency_slot=4,
            ),
            resolver_expression="self._root_resolver",
        )
        == "self._request_resolver.resolve_4()"
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=request_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=0,
                dependency_slot=5,
                dependency_requires_async=True,
            ),
            resolver_expression="self._root_resolver",
        )
        == "self.resolve_5()"
    )


def test_optimized_sync_dependency_expression_recursively_inlines_safe_transients() -> None:
    compiler = compiler_module.ResolversAssemblyCompiler()
    request_scope = _scope_plan(level=Scope.REQUEST.level, name="request")
    leaf_workflow = _workflow_plan(
        slot=90,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="concrete_type",
    )
    middle_dependency = _dependency(provides=leaf_workflow.provides, name="leaf")
    middle_workflow = _workflow_plan(
        slot=91,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="factory",
        dependencies=(middle_dependency,),
        dependency_slots=(leaf_workflow.slot,),
        dependency_requires_async=(False,),
        dependency_plans=(
            ProviderDependencyPlan(
                kind="provider",
                dependency=middle_dependency,
                dependency_index=0,
                dependency_slot=leaf_workflow.slot,
            ),
        ),
    )
    outer_dependency = _dependency(provides=middle_workflow.provides, name="middle")
    outer_workflow = _workflow_plan(
        slot=92,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="concrete_type",
        dependencies=(outer_dependency,),
        dependency_slots=(middle_workflow.slot,),
        dependency_requires_async=(False,),
        dependency_plans=(
            ProviderDependencyPlan(
                kind="provider",
                dependency=outer_dependency,
                dependency_index=0,
                dependency_slot=middle_workflow.slot,
            ),
        ),
    )
    runtime = _runtime(
        scopes=(_scope_plan(level=Scope.APP.level, name="app"), request_scope),
        workflows=(leaf_workflow, middle_workflow, outer_workflow),
    )
    dependency = _dependency(provides=outer_workflow.provides, name="outer")

    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=request_scope,
            dependency_plan=ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=0,
                dependency_slot=outer_workflow.slot,
            ),
            resolver_expression="self._root_resolver",
        )
        == "_provider_92(_provider_91(_provider_90()))"
    )
    bounded_plan = ProviderDependencyPlan(
        kind="provider",
        dependency=dependency,
        dependency_index=0,
        dependency_slot=outer_workflow.slot,
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=request_scope,
            dependency_plan=bounded_plan,
            resolver_expression="self._root_resolver",
            inline_state=compiler_module._SyncTransientInlineState(
                remaining_non_leaf_nodes=1,
                active_slots=set(),
            ),
        )
        == "_provider_92(self.resolve_91())"
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=request_scope,
            dependency_plan=bounded_plan,
            resolver_expression="self._root_resolver",
            inline_state=compiler_module._SyncTransientInlineState(
                remaining_non_leaf_nodes=8,
                active_slots={outer_workflow.slot},
            ),
        )
        == "self.resolve_92()"
    )
    assert (
        compiler._optimized_sync_dependency_expression(
            runtime=runtime,
            class_plan=request_scope,
            dependency_plan=bounded_plan,
            resolver_expression="self._root_resolver",
            inline_state=compiler_module._SyncTransientInlineState(
                remaining_non_leaf_nodes=8,
                active_slots=set(),
            ),
            inline_depth=compiler_module._SYNC_TRANSIENT_INLINE_MAX_DEPTH,
        )
        == "self.resolve_92()"
    )


def test_sync_dispatch_fusion_selects_largest_graph_before_cache_deterministically() -> None:
    class _Leaf:
        pass

    class _Middle:
        pass

    class _SelectedRoot:
        pass

    class _SmallRoot:
        pass

    class _TiedRoot:
        pass

    request_scope = _scope_plan(level=Scope.REQUEST.level, name="request")
    leaf_workflow = _workflow_plan(
        slot=90,
        provides=_Leaf,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="factory",
    )
    middle_dependency = _dependency(provides=_Leaf, name="leaf")
    middle_workflow = _workflow_plan(
        slot=91,
        provides=_Middle,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="factory",
        dependencies=(middle_dependency,),
        dependency_slots=(leaf_workflow.slot,),
        dependency_requires_async=(False,),
        dependency_plans=(
            ProviderDependencyPlan(
                kind="provider",
                dependency=middle_dependency,
                dependency_index=0,
                dependency_slot=leaf_workflow.slot,
            ),
        ),
    )
    selected_dependency = _dependency(provides=_Middle, name="middle")
    selected_workflow = _workflow_plan(
        slot=92,
        provides=_SelectedRoot,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="factory",
        dependencies=(selected_dependency,),
        dependency_slots=(middle_workflow.slot,),
        dependency_requires_async=(False,),
        dependency_plans=(
            ProviderDependencyPlan(
                kind="provider",
                dependency=selected_dependency,
                dependency_index=0,
                dependency_slot=middle_workflow.slot,
            ),
        ),
    )
    small_dependency = _dependency(provides=_Leaf, name="leaf")
    small_workflow = _workflow_plan(
        slot=94,
        provides=_SmallRoot,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="factory",
        dependencies=(small_dependency,),
        dependency_slots=(leaf_workflow.slot,),
        dependency_requires_async=(False,),
        dependency_plans=(
            ProviderDependencyPlan(
                kind="provider",
                dependency=small_dependency,
                dependency_index=0,
                dependency_slot=leaf_workflow.slot,
            ),
        ),
    )
    tied_dependency = _dependency(provides=_Middle, name="middle")
    tied_workflow = _workflow_plan(
        slot=95,
        provides=_TiedRoot,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="factory",
        dependencies=(tied_dependency,),
        dependency_slots=(middle_workflow.slot,),
        dependency_requires_async=(False,),
        dependency_plans=(
            ProviderDependencyPlan(
                kind="provider",
                dependency=tied_dependency,
                dependency_index=0,
                dependency_slot=middle_workflow.slot,
            ),
        ),
    )
    workflows = (
        tied_workflow,
        small_workflow,
        selected_workflow,
        middle_workflow,
        leaf_workflow,
    )
    runtime = _runtime(
        scopes=(_scope_plan(level=Scope.APP.level, name="app"), request_scope),
        workflows=workflows,
    )
    compiler = compiler_module.ResolversAssemblyCompiler()
    generated_globals = compiler._build_generated_globals(runtime=runtime)

    sync_dispatch = compiler._compile_dispatch_method(
        runtime=runtime,
        class_plan=request_scope,
        generated_globals=generated_globals,
        is_async=False,
    )
    async_dispatch = compiler._compile_dispatch_method(
        runtime=runtime,
        class_plan=request_scope,
        generated_globals=generated_globals,
        is_async=True,
    )

    sync_names = sync_dispatch.__code__.co_names
    assert "_provider_92" in sync_names
    assert "_provider_91" in sync_names
    assert "_provider_90" in sync_names
    assert "resolve_92" not in sync_names
    assert "_provider_94" not in sync_names
    assert "_provider_95" not in sync_names
    assert "resolve_94" in sync_names
    assert "resolve_95" in sync_names
    sync_instructions = tuple(dis.get_instructions(sync_dispatch))
    selected_dependency_loads = [
        index
        for index, instruction in enumerate(sync_instructions)
        if instruction.argval == "_dep_92_type"
    ]
    cache_load = next(
        index
        for index, instruction in enumerate(sync_instructions)
        if instruction.argval == "_last_sync_dependency"
    )
    assert len(selected_dependency_loads) == 1
    assert selected_dependency_loads[0] < cache_load
    assert "_provider_92" not in async_dispatch.__code__.co_names
    assert "aresolve_92" in async_dispatch.__code__.co_names

    ordered_runtime = _runtime(
        scopes=(_scope_plan(level=Scope.APP.level, name="app"), request_scope),
        workflows=tuple(reversed(workflows)),
    )
    ordered_dispatch = compiler._compile_dispatch_method(
        runtime=ordered_runtime,
        class_plan=request_scope,
        generated_globals=compiler._build_generated_globals(runtime=ordered_runtime),
        is_async=False,
    )
    assert "_provider_92" in ordered_dispatch.__code__.co_names
    assert "resolve_92" not in ordered_dispatch.__code__.co_names
    assert "_provider_95" not in ordered_dispatch.__code__.co_names


@pytest.mark.parametrize(
    ("replacement", "dependency_kind"),
    [
        (
            {
                "is_cached": True,
                "is_transient": False,
                "cache_owner_scope_level": Scope.REQUEST.level,
            },
            None,
        ),
        ({"requires_async": True, "is_provider_async": True}, None),
        ({"provider_is_inject_wrapper": True}, None),
        ({"needs_cleanup": True}, None),
        ({"scope_level": Scope.APP.level, "scope_name": "app"}, None),
        ({"max_required_scope_level": Scope.ACTION.level}, None),
        ({"uses_thread_lock": True}, None),
        ({"uses_async_lock": True}, None),
        ({"dispatch_kind": "equality_map"}, None),
        ({"dependency_plans": ()}, None),
        ({}, "all"),
        ({}, "variadic"),
    ],
    ids=(
        "cached",
        "async",
        "inject-wrapper",
        "cleanup",
        "other-scope",
        "deeper-scope",
        "thread-lock",
        "async-lock",
        "equality-dispatch",
        "incomplete-plan",
        "all-dependency",
        "variadic",
    ),
)
def test_sync_dispatch_fusion_keeps_unsafe_top_level_workflows(
    replacement: dict[str, Any],
    dependency_kind: str | None,
) -> None:
    class _Leaf:
        pass

    class _UnsafeRoot:
        pass

    request_scope = _scope_plan(level=Scope.REQUEST.level, name="request")
    leaf_workflow = _workflow_plan(
        slot=90,
        provides=_Leaf,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="factory",
    )
    dependency = _dependency(provides=_Leaf, name="leaf")
    unsafe_workflow = _workflow_plan(
        slot=93,
        provides=_UnsafeRoot,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="factory",
        dependencies=(dependency,),
        dependency_slots=(leaf_workflow.slot,),
        dependency_requires_async=(False,),
        dependency_plans=(
            ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=0,
                dependency_slot=leaf_workflow.slot,
            ),
        ),
    )
    if dependency_kind == "all":
        unsafe_workflow = replace(
            unsafe_workflow,
            dependency_plans=(
                ProviderDependencyPlan(
                    kind="all",
                    dependency=dependency,
                    dependency_index=0,
                    all_slots=(leaf_workflow.slot,),
                ),
            ),
        )
    elif dependency_kind == "variadic":
        variadic_dependency = _dependency(
            provides=_Leaf,
            name="leaves",
            kind=inspect.Parameter.VAR_POSITIONAL,
        )
        unsafe_workflow = replace(
            unsafe_workflow,
            dependencies=(variadic_dependency,),
            dependency_plans=(
                ProviderDependencyPlan(
                    kind="provider",
                    dependency=variadic_dependency,
                    dependency_index=0,
                    dependency_slot=leaf_workflow.slot,
                ),
            ),
        )
    else:
        unsafe_workflow = replace(unsafe_workflow, **replacement)

    filler_one = _workflow_plan(
        slot=91,
        provides=str,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="factory",
    )
    filler_two = _workflow_plan(
        slot=92,
        provides=bytes,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="factory",
    )
    runtime = _runtime(
        scopes=(_scope_plan(level=Scope.APP.level, name="app"), request_scope),
        workflows=(leaf_workflow, filler_one, filler_two, unsafe_workflow),
    )
    compiler = compiler_module.ResolversAssemblyCompiler()
    dispatch = compiler._compile_dispatch_method(
        runtime=runtime,
        class_plan=request_scope,
        generated_globals=compiler._build_generated_globals(runtime=runtime),
        is_async=False,
    )

    assert "_provider_93" not in dispatch.__code__.co_names
    assert "resolve_93" in dispatch.__code__.co_names


@pytest.mark.parametrize("bound_kind", ["dispatch-cache", "call-count", "ast-nodes"])
def test_sync_dispatch_fusion_respects_dispatch_and_expression_bounds(
    bound_kind: str,
) -> None:
    class _Leaf:
        pass

    class _BoundedRoot:
        pass

    request_scope = _scope_plan(level=Scope.REQUEST.level, name="request")
    leaf_workflows: list[ProviderWorkflowPlan] = []
    dependencies: list[ProviderDependency] = []
    dependency_plans: list[ProviderDependencyPlan] = []
    if bound_kind == "call-count":
        leaf_count = compiler_module._SYNC_DISPATCH_FUSION_MAX_CALLS
    else:
        leaf_count = 1
    for index in range(leaf_count):
        slot = 90 + index
        leaf_workflow = _workflow_plan(
            slot=slot,
            provides=type(f"_Leaf{index}", (), {}),
            scope_level=Scope.REQUEST.level,
            is_cached=False,
            cache_owner_scope_level=None,
            provider_attribute="factory",
        )
        dependency = _dependency(provides=leaf_workflow.provides, name=f"leaf_{index}")
        leaf_workflows.append(leaf_workflow)
        dependencies.append(dependency)
        dependency_plans.append(
            ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=index,
                dependency_slot=slot,
            ),
        )

    if bound_kind == "ast-nodes":
        literal_dependency = _dependency(provides=tuple[object, ...], name="values")
        dependencies.append(literal_dependency)
        dependency_plans.append(
            ProviderDependencyPlan(
                kind="literal",
                dependency=literal_dependency,
                dependency_index=1,
                literal_expression="(" + ", ".join("None" for _ in range(130)) + ",)",
            ),
        )

    root_slot = 90 + leaf_count
    root_workflow = _workflow_plan(
        slot=root_slot,
        provides=_BoundedRoot,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="factory",
        dependencies=tuple(dependencies),
        dependency_slots=tuple(plan.dependency_slot for plan in dependency_plans),
        dependency_requires_async=tuple(False for _ in dependency_plans),
        dependency_plans=tuple(dependency_plans),
    )
    workflows: list[ProviderWorkflowPlan] = [*leaf_workflows, root_workflow]
    if bound_kind != "call-count":
        workflows.extend(
            (
                _workflow_plan(
                    slot=root_slot + 1,
                    provides=str,
                    scope_level=Scope.REQUEST.level,
                    is_cached=False,
                    cache_owner_scope_level=None,
                    provider_attribute="factory",
                ),
                _workflow_plan(
                    slot=root_slot + 2,
                    provides=bytes,
                    scope_level=Scope.REQUEST.level,
                    is_cached=False,
                    cache_owner_scope_level=None,
                    provider_attribute="factory",
                ),
            ),
        )
    if bound_kind == "dispatch-cache":
        workflows = [*leaf_workflows, root_workflow]

    runtime = _runtime(
        scopes=(_scope_plan(level=Scope.APP.level, name="app"), request_scope),
        workflows=tuple(workflows),
    )
    compiler = compiler_module.ResolversAssemblyCompiler()
    dispatch = compiler._compile_dispatch_method(
        runtime=runtime,
        class_plan=request_scope,
        generated_globals=compiler._build_generated_globals(runtime=runtime),
        is_async=False,
    )

    assert f"_provider_{root_slot}" not in dispatch.__code__.co_names
    assert f"resolve_{root_slot}" in dispatch.__code__.co_names


@pytest.mark.parametrize(
    "unsafe_workflow",
    [
        _workflow_plan(
            slot=93,
            scope_level=Scope.REQUEST.level,
            is_cached=True,
            cache_owner_scope_level=Scope.REQUEST.level,
            provider_attribute="factory",
            dependencies=(_dependency(name="value"),),
            dependency_slots=(90,),
            dependency_requires_async=(False,),
            dependency_plans=(
                ProviderDependencyPlan(
                    kind="provider",
                    dependency=_dependency(name="value"),
                    dependency_index=0,
                    dependency_slot=90,
                ),
            ),
        ),
        _workflow_plan(
            slot=94,
            scope_level=Scope.REQUEST.level,
            is_cached=False,
            cache_owner_scope_level=None,
            provider_attribute="factory",
            requires_async=True,
            is_provider_async=True,
            dependencies=(_dependency(name="value"),),
            dependency_slots=(90,),
            dependency_requires_async=(False,),
            dependency_plans=(
                ProviderDependencyPlan(
                    kind="provider",
                    dependency=_dependency(name="value"),
                    dependency_index=0,
                    dependency_slot=90,
                ),
            ),
        ),
        _workflow_plan(
            slot=95,
            scope_level=Scope.REQUEST.level,
            is_cached=False,
            cache_owner_scope_level=None,
            provider_attribute="factory",
            provider_is_inject_wrapper=True,
            dependencies=(_dependency(name="value"),),
            dependency_slots=(90,),
            dependency_requires_async=(False,),
            dependency_plans=(
                ProviderDependencyPlan(
                    kind="provider",
                    dependency=_dependency(name="value"),
                    dependency_index=0,
                    dependency_slot=90,
                ),
            ),
        ),
        replace(
            _workflow_plan(
                slot=96,
                scope_level=Scope.REQUEST.level,
                is_cached=False,
                cache_owner_scope_level=None,
                provider_attribute="factory",
                dependencies=(_dependency(name="value"),),
                dependency_slots=(90,),
                dependency_requires_async=(False,),
                dependency_plans=(
                    ProviderDependencyPlan(
                        kind="provider",
                        dependency=_dependency(name="value"),
                        dependency_index=0,
                        dependency_slot=90,
                    ),
                ),
            ),
            needs_cleanup=True,
        ),
        _workflow_plan(
            slot=97,
            scope_level=Scope.REQUEST.level,
            is_cached=False,
            cache_owner_scope_level=None,
            provider_attribute="factory",
            dependencies=(_dependency(name="value"),),
            dependency_slots=(90,),
            dependency_requires_async=(False,),
            dependency_plans=(),
        ),
        _workflow_plan(
            slot=98,
            scope_level=Scope.REQUEST.level,
            is_cached=False,
            cache_owner_scope_level=None,
            provider_attribute="factory",
            dependencies=(_dependency(name="value"),),
            dependency_slots=(None,),
            dependency_requires_async=(False,),
            dependency_plans=(
                ProviderDependencyPlan(
                    kind="all",
                    dependency=_dependency(name="value"),
                    dependency_index=0,
                    all_slots=(90,),
                ),
            ),
        ),
    ],
    ids=(
        "cached",
        "async",
        "inject-wrapper",
        "cleanup",
        "incomplete-plan",
        "all-dependency",
    ),
)
def test_optimized_sync_dependency_expression_keeps_unsafe_transient_boundaries(
    unsafe_workflow: ProviderWorkflowPlan,
) -> None:
    compiler = compiler_module.ResolversAssemblyCompiler()
    request_scope = _scope_plan(level=Scope.REQUEST.level, name="request")
    leaf_workflow = _workflow_plan(
        slot=90,
        scope_level=Scope.REQUEST.level,
        is_cached=False,
        cache_owner_scope_level=None,
        provider_attribute="factory",
    )
    runtime = _runtime(
        scopes=(_scope_plan(level=Scope.APP.level, name="app"), request_scope),
        workflows=(leaf_workflow, unsafe_workflow),
    )
    dependency = _dependency(provides=unsafe_workflow.provides)
    expression = compiler._optimized_sync_dependency_expression(
        runtime=runtime,
        class_plan=request_scope,
        dependency_plan=ProviderDependencyPlan(
            kind="provider",
            dependency=dependency,
            dependency_index=0,
            dependency_slot=unsafe_workflow.slot,
        ),
        resolver_expression="self._root_resolver",
    )

    assert isinstance(expression, str)
    assert f"_provider_{unsafe_workflow.slot}(" not in expression


def _cached_fusion_test_workflow(
    *,
    slot: int,
    provides: Any,
    children: tuple[ProviderWorkflowPlan, ...] = (),
    dependency_kinds: tuple[inspect._ParameterKind, ...] | None = None,
) -> ProviderWorkflowPlan:
    if dependency_kinds is None:
        dependency_kinds = tuple(inspect.Parameter.POSITIONAL_OR_KEYWORD for _ in children)
    dependencies = tuple(
        _dependency(
            provides=child.provides,
            name=f"dependency_{index}",
            kind=parameter_kind,
        )
        for index, (child, parameter_kind) in enumerate(
            zip(children, dependency_kinds, strict=True),
        )
    )
    return replace(
        _workflow_plan(
            slot=slot,
            provides=provides,
            provider_attribute="factory",
            scope_level=Scope.REQUEST.level,
            cache_owner_scope_level=Scope.REQUEST.level,
            dependencies=dependencies,
            dependency_slots=tuple(child.slot for child in children),
            dependency_requires_async=tuple(False for _ in children),
            dependency_plans=tuple(
                ProviderDependencyPlan(
                    kind="provider",
                    dependency=dependency,
                    dependency_index=index,
                    dependency_slot=child.slot,
                )
                for index, (dependency, child) in enumerate(
                    zip(dependencies, children, strict=True),
                )
            ),
        ),
        lock_mode=LockMode.NONE,
        effective_lock_mode=LockMode.NONE,
    )


def test_sync_cached_dispatch_fusion_supports_zero_and_one_child() -> None:
    class _Leaf:
        pass

    class _OneChild:
        pass

    class _ZeroChild:
        pass

    root_scope = _scope_plan(level=Scope.APP.level, name="app")
    request_scope = _scope_plan(level=Scope.REQUEST.level, name="request")
    leaf = _cached_fusion_test_workflow(slot=80, provides=_Leaf)
    one_child = _cached_fusion_test_workflow(
        slot=81,
        provides=_OneChild,
        children=(leaf,),
    )
    zero_child = _cached_fusion_test_workflow(slot=82, provides=_ZeroChild)
    compiler = compiler_module.ResolversAssemblyCompiler()

    for workflows in ((zero_child,), (leaf, one_child)):
        for ordered_workflows in (workflows, tuple(reversed(workflows))):
            runtime = _runtime(
                scopes=(root_scope, request_scope),
                workflows=ordered_workflows,
            )
            generated_globals = compiler._build_generated_globals(runtime=runtime)
            sync_dispatch = compiler._compile_dispatch_method(
                runtime=runtime,
                class_plan=request_scope,
                generated_globals=generated_globals,
                is_async=False,
            )
            async_dispatch = compiler._compile_dispatch_method(
                runtime=runtime,
                class_plan=request_scope,
                generated_globals=generated_globals,
                is_async=True,
            )
            target = zero_child if len(workflows) == 1 else one_child

            assert f"_provider_{target.slot}" in sync_dispatch.__code__.co_names
            assert f"resolve_{target.slot}" not in sync_dispatch.__code__.co_names
            assert f"_provider_{target.slot}" not in async_dispatch.__code__.co_names
            assert f"aresolve_{target.slot}" in async_dispatch.__code__.co_names

            if target is one_child:
                instructions = tuple(dis.get_instructions(sync_dispatch))
                assert "_provider_80" in sync_dispatch.__code__.co_names
                assert (
                    sum(
                        instruction.opname == "LOAD_ATTR" and instruction.argval == "_cache_80"
                        for instruction in instructions
                    )
                    == 2
                )


def test_sync_cached_generator_dispatch_fusion_accepts_only_exact_safe_shape() -> None:
    compiler = compiler_module.ResolversAssemblyCompiler()
    root_scope = _scope_plan(level=Scope.APP.level, name="app")
    request_scope = _scope_plan(level=Scope.REQUEST.level, name="request")
    safe_workflow = replace(
        _cached_fusion_test_workflow(slot=83, provides=bytearray),
        provider_attribute="generator",
        needs_cleanup=True,
    )

    def fusion_candidate(
        workflow: ProviderWorkflowPlan,
        *,
        class_plan: ScopePlan = request_scope,
        identity_workflows: tuple[ProviderWorkflowPlan, ...] | None = None,
        has_cleanup: bool = True,
    ) -> tuple[ProviderWorkflowPlan, tuple[ast.stmt, ...]] | None:
        runtime = _runtime(
            scopes=(root_scope, request_scope),
            workflows=(workflow,),
        )
        runtime.has_cleanup = has_cleanup
        if identity_workflows is None:
            identity_workflows = (workflow,) if workflow.dispatch_kind == "identity" else ()
        return compiler._sync_cached_generator_dispatch_fusion_candidate(
            runtime=runtime,
            class_plan=class_plan,
            identity_workflows=identity_workflows,
        )

    candidate = fusion_candidate(safe_workflow)
    assert candidate is not None
    assert candidate[0] is safe_workflow

    dependency = _dependency(provides=int)
    dependency_plan = ProviderDependencyPlan(
        kind="provider",
        dependency=dependency,
        dependency_index=0,
        dependency_slot=84,
    )
    unsafe_workflows = (
        replace(safe_workflow, scope_level=Scope.APP.level),
        replace(safe_workflow, cache_owner_scope_level=Scope.APP.level),
        replace(safe_workflow, max_required_scope_level=Scope.REQUEST.level + 1),
        replace(safe_workflow, is_cached=False, cache_owner_scope_level=None),
        replace(safe_workflow, is_transient=True),
        replace(safe_workflow, lock_mode="auto"),
        replace(safe_workflow, effective_lock_mode=LockMode.THREAD),
        replace(safe_workflow, uses_thread_lock=True),
        replace(safe_workflow, uses_async_lock=True),
        replace(safe_workflow, requires_async=True),
        replace(safe_workflow, is_provider_async=True),
        replace(safe_workflow, provider_attribute="factory"),
        replace(safe_workflow, provider_is_inject_wrapper=True),
        replace(safe_workflow, needs_cleanup=False),
        replace(
            safe_workflow,
            dependencies=(dependency,),
            dependency_slots=(84,),
            dependency_requires_async=(False,),
        ),
        replace(safe_workflow, dependency_plans=(dependency_plan,)),
        replace(safe_workflow, sync_arguments=("self.resolve_84()",)),
        replace(safe_workflow, dispatch_kind="equality_map"),
    )
    for unsafe_workflow in unsafe_workflows:
        assert fusion_candidate(unsafe_workflow) is None

    assert fusion_candidate(safe_workflow, class_plan=root_scope) is None
    assert fusion_candidate(safe_workflow, identity_workflows=()) is None
    assert fusion_candidate(safe_workflow, has_cleanup=False) is None

    cloned_workflow = replace(safe_workflow)
    assert fusion_candidate(safe_workflow, identity_workflows=(cloned_workflow,)) is None

    second_workflow = replace(safe_workflow, slot=84, provides=bytes)
    multiple_runtime = _runtime(
        scopes=(root_scope, request_scope),
        workflows=(safe_workflow, second_workflow),
    )
    assert (
        compiler._sync_cached_generator_dispatch_fusion_candidate(
            runtime=multiple_runtime,
            class_plan=request_scope,
            identity_workflows=(safe_workflow, second_workflow),
        )
        is None
    )


def test_specialized_sync_generator_body_lines_cover_cache_and_cleanup_variants() -> None:
    compiler = compiler_module.ResolversAssemblyCompiler()
    root_scope = _scope_plan(level=Scope.APP.level, name="app")
    root_workflow = _workflow_plan(
        slot=84,
        provider_attribute="generator",
        scope_level=Scope.APP.level,
        cache_owner_scope_level=Scope.APP.level,
    )
    root_runtime = _runtime(scopes=(root_scope,), workflows=(root_workflow,))

    root_lines = compiler._specialized_sync_generator_body_lines(
        runtime=root_runtime,
        workflow=root_workflow,
        arguments="",
    )

    assert "self._cache_84 = value" in root_lines
    assert "self.resolve_84 = lambda: value" in root_lines

    transient_workflow = _workflow_plan(
        slot=85,
        provider_attribute="generator",
        is_cached=False,
        cache_owner_scope_level=None,
    )
    transient_runtime = _runtime(scopes=(root_scope,), workflows=(transient_workflow,))
    transient_runtime.has_cleanup = False

    assert compiler._specialized_sync_generator_body_lines(
        runtime=transient_runtime,
        workflow=transient_workflow,
        arguments="",
    ) == [
        "provider_gen = _provider_85()",
        "value = next(provider_gen)",
        "return value",
    ]


def test_sync_cached_fusion_workflow_safety_rejects_every_unsafe_shape() -> None:
    compiler = compiler_module.ResolversAssemblyCompiler()
    request_scope = _scope_plan(level=Scope.REQUEST.level, name="request")
    child = _cached_fusion_test_workflow(slot=80, provides=bytes)
    safe_workflow = _cached_fusion_test_workflow(
        slot=81,
        provides=bytearray,
        children=(child,),
    )
    assert compiler._sync_cached_fusion_workflow_is_safe(
        class_plan=request_scope,
        workflow=safe_workflow,
    )

    dependency_plan = safe_workflow.dependency_plans[0]
    positional_variadic = _dependency(
        provides=child.provides,
        name="args",
        kind=inspect.Parameter.VAR_POSITIONAL,
    )
    keyword_variadic = _dependency(
        provides=child.provides,
        name="kwargs",
        kind=inspect.Parameter.VAR_KEYWORD,
    )
    mismatched_dependency = _dependency(provides=child.provides, name="other")
    unsafe_workflows = (
        replace(safe_workflow, scope_level=Scope.APP.level),
        replace(safe_workflow, cache_owner_scope_level=Scope.APP.level),
        replace(safe_workflow, max_required_scope_level=Scope.REQUEST.level + 1),
        replace(safe_workflow, is_cached=False),
        replace(safe_workflow, is_transient=True),
        replace(safe_workflow, effective_lock_mode=LockMode.THREAD),
        replace(safe_workflow, uses_thread_lock=True),
        replace(safe_workflow, uses_async_lock=True),
        replace(safe_workflow, requires_async=True),
        replace(safe_workflow, is_provider_async=True),
        replace(safe_workflow, provider_attribute="instance"),
        replace(safe_workflow, provider_is_inject_wrapper=True),
        replace(safe_workflow, needs_cleanup=True),
        replace(safe_workflow, dispatch_kind="equality_map"),
        replace(safe_workflow, dependency_plans=()),
        replace(
            safe_workflow,
            dependency_plans=(replace(dependency_plan, dependency=mismatched_dependency),),
        ),
        replace(
            safe_workflow,
            dependencies=(positional_variadic,),
            dependency_plans=(replace(dependency_plan, dependency=positional_variadic),),
        ),
        replace(
            safe_workflow,
            dependencies=(keyword_variadic,),
            dependency_plans=(replace(dependency_plan, dependency=keyword_variadic),),
        ),
        replace(
            safe_workflow,
            dependency_plans=(replace(dependency_plan, dependency_requires_async=True),),
        ),
    )

    for unsafe_workflow in unsafe_workflows:
        assert not compiler._sync_cached_fusion_workflow_is_safe(
            class_plan=request_scope,
            workflow=unsafe_workflow,
        )


def test_sync_cached_dispatch_fusion_rejects_unsafe_shapes_and_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ChildA:
        pass

    class _ChildB:
        pass

    class _Target:
        pass

    compiler = compiler_module.ResolversAssemblyCompiler()
    root_scope = _scope_plan(level=Scope.APP.level, name="app")
    request_scope = _scope_plan(level=Scope.REQUEST.level, name="request")
    child_a = _cached_fusion_test_workflow(slot=90, provides=_ChildA)
    child_b = _cached_fusion_test_workflow(slot=91, provides=_ChildB)
    target = _cached_fusion_test_workflow(
        slot=92,
        provides=_Target,
        children=(child_a, child_b),
    )

    def fusion_candidate(
        *,
        workflows: tuple[ProviderWorkflowPlan, ...],
        class_plan: ScopePlan = request_scope,
    ) -> tuple[ProviderWorkflowPlan, tuple[ast.stmt, ...]] | None:
        runtime = _runtime(scopes=(root_scope, request_scope), workflows=workflows)
        identity_workflows = tuple(
            workflow
            for workflow in compiler_module._dispatch_workflows(
                plan=runtime.plan,
                class_plan=class_plan,
            )
            if workflow.dispatch_kind == "identity"
        )
        return compiler._sync_cached_dispatch_fusion_candidate(
            runtime=runtime,
            class_plan=class_plan,
            identity_workflows=identity_workflows,
        )

    def assert_safe_fallback_selected(
        *,
        workflows: tuple[ProviderWorkflowPlan, ...],
    ) -> None:
        candidate = fusion_candidate(workflows=workflows)

        assert candidate is not None
        assert candidate[0].slot == child_b.slot

    assert fusion_candidate(workflows=(child_a, child_b, target)) is not None
    assert (
        fusion_candidate(
            workflows=(child_a, child_b, target),
            class_plan=root_scope,
        )
        is None
    )
    transient = replace(
        child_a,
        slot=93,
        lifetime=Lifetime.TRANSIENT,
        is_cached=False,
        is_transient=True,
        cache_owner_scope_level=None,
    )
    assert fusion_candidate(workflows=(child_a, child_b, target, transient)) is None

    non_provider_plan = replace(target.dependency_plans[0], kind="literal")
    missing_slot_plan = replace(target.dependency_plans[0], dependency_slot=None)
    unknown_slot_plan = replace(target.dependency_plans[0], dependency_slot=999)
    keyword_only_target = _cached_fusion_test_workflow(
        slot=92,
        provides=_Target,
        children=(child_a, child_b),
        dependency_kinds=(
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ),
    )
    self_child_target = replace(
        target,
        dependency_plans=(
            replace(target.dependency_plans[0], dependency_slot=target.slot),
            target.dependency_plans[1],
        ),
        dependency_slots=(target.slot, child_b.slot),
    )
    too_many_child_dependencies = tuple(
        _dependency(provides=_ChildB, name=f"nested_{index}")
        for index in range(compiler_module._SYNC_CACHED_FUSION_MAX_CHILD_DEPENDENCIES + 1)
    )
    oversized_child = replace(
        child_a,
        dependencies=too_many_child_dependencies,
        dependency_slots=tuple(child_b.slot for _ in too_many_child_dependencies),
        dependency_requires_async=tuple(False for _ in too_many_child_dependencies),
        dependency_plans=tuple(
            ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=index,
                dependency_slot=child_b.slot,
            )
            for index, dependency in enumerate(too_many_child_dependencies)
        ),
    )
    unsafe_child = replace(child_a, effective_lock_mode=LockMode.THREAD)
    target_variants = (
        replace(target, effective_lock_mode=LockMode.THREAD),
        replace(target, dependency_order_is_signature_order=False),
        replace(
            target,
            dependency_plans=(non_provider_plan, target.dependency_plans[1]),
        ),
        replace(
            target,
            dependency_plans=(missing_slot_plan, target.dependency_plans[1]),
        ),
        replace(
            target,
            dependency_plans=(unknown_slot_plan, target.dependency_plans[1]),
        ),
        keyword_only_target,
    )
    for target_variant in target_variants:
        assert_safe_fallback_selected(workflows=(child_a, child_b, target_variant))

    assert_safe_fallback_selected(workflows=(child_a, child_b, self_child_target))
    assert_safe_fallback_selected(workflows=(oversized_child, child_b, target))
    assert_safe_fallback_selected(workflows=(unsafe_child, child_b, target))

    monkeypatch.setattr(compiler_module, "_SYNC_CACHED_FUSION_MAX_AST_NODES", 1)
    assert fusion_candidate(workflows=(child_a, child_b, target)) is None


def test_sync_cached_dispatch_fusion_selects_largest_then_highest_slot() -> None:
    child_types = tuple(type(f"_Child{index}", (), {}) for index in range(3))
    target_types = tuple(type(f"_Target{index}", (), {}) for index in range(4))
    children = tuple(
        _cached_fusion_test_workflow(slot=200 + index, provides=child_type)
        for index, child_type in enumerate(child_types)
    )
    targets = (
        _cached_fusion_test_workflow(
            slot=210,
            provides=target_types[0],
            children=children[:2],
        ),
        _cached_fusion_test_workflow(
            slot=211,
            provides=target_types[1],
            children=children,
        ),
        _cached_fusion_test_workflow(
            slot=212,
            provides=target_types[2],
            children=children[:2],
        ),
        _cached_fusion_test_workflow(
            slot=213,
            provides=target_types[3],
            children=children,
        ),
    )
    workflows = (*children, *targets)
    root_scope = _scope_plan(level=Scope.APP.level, name="app")
    request_scope = _scope_plan(level=Scope.REQUEST.level, name="request")
    compiler = compiler_module.ResolversAssemblyCompiler()

    for ordered_workflows in (workflows, tuple(reversed(workflows))):
        runtime = _runtime(
            scopes=(root_scope, request_scope),
            workflows=ordered_workflows,
        )
        dispatch = compiler._compile_dispatch_method(
            runtime=runtime,
            class_plan=request_scope,
            generated_globals=compiler._build_generated_globals(runtime=runtime),
            is_async=False,
        )

        assert "_provider_213" in dispatch.__code__.co_names
        assert "resolve_213" not in dispatch.__code__.co_names
        assert "resolve_210" in dispatch.__code__.co_names
        assert "resolve_211" in dispatch.__code__.co_names
        assert "resolve_212" in dispatch.__code__.co_names


def test_cached_dispatch_fusion_is_bounded_deterministic_and_sync_only() -> None:
    class _Left:
        pass

    class _Right:
        pass

    class _Target:
        pass

    request_scope = _scope_plan(level=Scope.REQUEST.level, name="request")
    left_workflow = replace(
        _workflow_plan(
            slot=90,
            provides=_Left,
            provider_attribute="factory",
            scope_level=Scope.REQUEST.level,
            cache_owner_scope_level=Scope.REQUEST.level,
        ),
        lock_mode=LockMode.NONE,
        effective_lock_mode=LockMode.NONE,
    )
    right_workflow = replace(left_workflow, slot=91, provides=_Right)
    dependencies = (
        _dependency(provides=_Left, name="left"),
        _dependency(provides=_Right, name="right"),
    )
    target_workflow = replace(
        _workflow_plan(
            slot=92,
            provides=_Target,
            provider_attribute="factory",
            scope_level=Scope.REQUEST.level,
            cache_owner_scope_level=Scope.REQUEST.level,
            dependencies=dependencies,
            dependency_slots=(left_workflow.slot, right_workflow.slot),
            dependency_requires_async=(False, False),
            dependency_plans=tuple(
                ProviderDependencyPlan(
                    kind="provider",
                    dependency=dependency,
                    dependency_index=index,
                    dependency_slot=slot,
                )
                for index, (dependency, slot) in enumerate(
                    zip(
                        dependencies,
                        (left_workflow.slot, right_workflow.slot),
                        strict=True,
                    ),
                )
            ),
        ),
        lock_mode=LockMode.NONE,
        effective_lock_mode=LockMode.NONE,
    )
    workflows = (left_workflow, right_workflow, target_workflow)
    compiler = compiler_module.ResolversAssemblyCompiler()

    for ordered_workflows in (workflows, tuple(reversed(workflows))):
        runtime = _runtime(
            scopes=(_scope_plan(level=Scope.APP.level, name="app"), request_scope),
            workflows=ordered_workflows,
        )
        generated_globals = compiler._build_generated_globals(runtime=runtime)
        sync_dispatch = compiler._compile_dispatch_method(
            runtime=runtime,
            class_plan=request_scope,
            generated_globals=generated_globals,
            is_async=False,
        )
        async_dispatch = compiler._compile_dispatch_method(
            runtime=runtime,
            class_plan=request_scope,
            generated_globals=generated_globals,
            is_async=True,
        )

        assert "_provider_92" in sync_dispatch.__code__.co_names
        assert "_provider_90" in sync_dispatch.__code__.co_names
        assert "_provider_91" in sync_dispatch.__code__.co_names
        assert "resolve_92" not in sync_dispatch.__code__.co_names
        instructions = tuple(dis.get_instructions(sync_dispatch))
        instruction_index = {
            instruction.argval: index
            for index, instruction in enumerate(instructions)
            if instruction.argval
            in {
                "_dep_90_type",
                "_dep_91_type",
                "_dep_92_type",
                "_provider_90",
                "_provider_91",
            }
        }
        assert instruction_index["_dep_92_type"] < instruction_index["_dep_90_type"]
        assert instruction_index["_dep_92_type"] < instruction_index["_dep_91_type"]
        assert instruction_index["_provider_90"] < instruction_index["_dep_90_type"]
        assert instruction_index["_provider_91"] < instruction_index["_dep_91_type"]
        assert (
            sum(
                instruction.opname == "LOAD_ATTR" and instruction.argval == "_cache_90"
                for instruction in instructions
            )
            >= 2
        )
        assert (
            sum(
                instruction.opname == "LOAD_ATTR" and instruction.argval == "_cache_91"
                for instruction in instructions
            )
            >= 2
        )
        assert "_provider_92" not in async_dispatch.__code__.co_names
        assert "aresolve_92" in async_dispatch.__code__.co_names

    oversized_dependencies = tuple(
        _dependency(provides=type(f"_Child{index}", (), {}), name=f"child_{index}")
        for index in range(compiler_module._SYNC_CACHED_FUSION_MAX_CHILDREN + 1)
    )
    oversized_children = tuple(
        replace(
            left_workflow,
            slot=100 + index,
            provides=dependency.provides,
        )
        for index, dependency in enumerate(oversized_dependencies)
    )
    oversized_target = replace(
        target_workflow,
        slot=120,
        dependencies=oversized_dependencies,
        dependency_slots=tuple(workflow.slot for workflow in oversized_children),
        dependency_requires_async=tuple(False for _ in oversized_children),
        dependency_plans=tuple(
            ProviderDependencyPlan(
                kind="provider",
                dependency=dependency,
                dependency_index=index,
                dependency_slot=workflow.slot,
            )
            for index, (dependency, workflow) in enumerate(
                zip(oversized_dependencies, oversized_children, strict=True),
            )
        ),
    )
    oversized_runtime = _runtime(
        scopes=(_scope_plan(level=Scope.APP.level, name="app"), request_scope),
        workflows=(*oversized_children, oversized_target),
    )
    oversized_dispatch = compiler._compile_dispatch_method(
        runtime=oversized_runtime,
        class_plan=request_scope,
        generated_globals=compiler._build_generated_globals(runtime=oversized_runtime),
        is_async=False,
    )
    assert "_provider_120" not in oversized_dispatch.__code__.co_names
    assert "resolve_120" in oversized_dispatch.__code__.co_names


def test_dispatch_cache_is_disabled_only_when_every_workflow_is_cached() -> None:
    root_scope = _scope_plan(level=Scope.APP.level, name="app")
    request_scope = _scope_plan(level=Scope.REQUEST.level, name="request")
    cached_workflows = tuple(_workflow_plan(slot=slot) for slot in range(1, 5))

    for workflow_count in (1, 4):
        plan = _generation_plan(
            scopes=(root_scope, request_scope),
            workflows=cached_workflows[:workflow_count],
        )
        assert not compiler_module._dispatch_cache_enabled_for_class(
            plan=plan,
            class_plan=root_scope,
        )
        assert not compiler_module._dispatch_cache_enabled_for_class(
            plan=plan,
            class_plan=request_scope,
        )

    transient_workflow = replace(
        cached_workflows[0],
        lifetime=Lifetime.TRANSIENT,
        is_cached=False,
        is_transient=True,
        cache_owner_scope_level=None,
    )
    one_transient_plan = _generation_plan(
        scopes=(root_scope, request_scope),
        workflows=(transient_workflow,),
    )
    assert compiler_module._dispatch_cache_enabled_for_class(
        plan=one_transient_plan,
        class_plan=request_scope,
    )

    mixed_plan = _generation_plan(
        scopes=(root_scope, request_scope),
        workflows=(*cached_workflows[:3], transient_workflow),
    )
    assert compiler_module._dispatch_cache_enabled_for_class(
        plan=mixed_plan,
        class_plan=root_scope,
    )
    assert compiler_module._dispatch_cache_enabled_for_class(
        plan=mixed_plan,
        class_plan=request_scope,
    )


@pytest.mark.asyncio
async def test_all_cached_dispatch_omits_dead_cache_and_preserves_equality_lookup() -> None:
    class _EqualityKey:
        def __init__(self, value: int) -> None:
            self.value = value

        def __eq__(self, other: object) -> bool:
            return isinstance(other, _EqualityKey) and self.value == other.value

        def __hash__(self) -> int:
            return hash(self.value)

    registration_keys = tuple(_EqualityKey(value) for value in range(4))
    registered_values = tuple(object() for _ in registration_keys)
    container = Container(use_resolver_context=False)
    for key, value in zip(registration_keys, registered_values, strict=True):
        container.add_instance(value, provides=key)
    resolver = container.compile()

    with resolver.enter_scope(Scope.REQUEST) as request_scope:
        request_slots = cast("Any", type(request_scope)).__slots__
        assert "_last_sync_dependency" not in request_slots
        assert "_last_sync_method" not in request_slots
        assert "_last_async_dependency" not in request_slots
        assert "_last_async_method" not in request_slots
        assert "_last_sync_dependency" not in request_scope.resolve.__code__.co_names
        assert "_last_async_dependency" not in request_scope.aresolve.__code__.co_names

        lookup_key = _EqualityKey(registration_keys[0].value)
        assert lookup_key is not registration_keys[0]
        assert request_scope.resolve(lookup_key) is registered_values[0]
        assert await request_scope.aresolve(lookup_key) is registered_values[0]

        with pytest.raises(DIWireDependencyNotRegisteredError, match="is not registered"):
            request_scope.resolve(_EqualityKey(99))
        with pytest.raises(DIWireDependencyNotRegisteredError, match="is not registered"):
            await request_scope.aresolve(_EqualityKey(99))


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
        parent_resolver=None,
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
        parent_resolver=None,
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
        parent_resolver=parent_tenant,
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
        parent_resolver=parent_session,
    )
    assert request_resolver_2_any._tenant_resolver == "tenant-owner"

    request_resolver_3 = _RequestResolver()
    request_resolver_3_any = cast("Any", request_resolver_3)
    compiler_module._resolver_init(
        request_resolver_3,
        root_resolver="root",
        cleanup_enabled=True,
        parent_resolver=None,
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
    root_resolver._cleanup_enabled = True

    assert isinstance(compiler_module._resolver_enter_scope(root_resolver, None), _Ctor)
    assert isinstance(compiler_module._resolver_enter_scope(root_resolver, 3), _Ctor)

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
    stateless_root._cleanup_enabled = True
    stateless_root._scope_resolver_3 = "pooled-request"
    stateless_root._scope_resolver_4 = "pooled-session"

    created = compiler_module._resolver_enter_scope(stateless_root, 4)
    assert created == "pooled-session"

    assert (
        compiler_module._instantiate_scope_transition(
            runtime=stateless_runtime,
            current_resolver=stateless_root,
            target_scope=request_scope,
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


def test_cleanup_sync_generator_successful_throw_branches() -> None:
    class _GenStop:
        def throw(
            self,
            _exc_type: type[BaseException] | None,
            _exc_value: BaseException,
            _traceback: object,
        ) -> None:
            raise StopIteration

        def close(self) -> None:
            return None

    compiler_module._cleanup_sync_generator(
        provider_gen=_GenStop(),
        exc_type=ValueError,
        exc_value=None,
        traceback=None,
    )

    class _GenRuntimeSame:
        def throw(
            self,
            _exc_type: type[BaseException] | None,
            exc_value: BaseException,
            _traceback: object,
        ) -> None:
            raise RuntimeError from exc_value

        def close(self) -> None:
            return None

    compiler_module._cleanup_sync_generator(
        provider_gen=_GenRuntimeSame(),
        exc_type=StopIteration,
        exc_value=StopIteration(),
        traceback=None,
    )

    class _GenRuntimeIdentity:
        def throw(
            self,
            _exc_type: type[BaseException] | None,
            exc_value: BaseException,
            _traceback: object,
        ) -> None:
            raise cast("RuntimeError", exc_value)

        def close(self) -> None:
            return None

    runtime_exc = RuntimeError("same")
    compiler_module._cleanup_sync_generator(
        provider_gen=_GenRuntimeIdentity(),
        exc_type=RuntimeError,
        exc_value=runtime_exc,
        traceback=None,
    )

    class _GenBaseIdentity:
        def throw(
            self,
            _exc_type: type[BaseException] | None,
            exc_value: BaseException,
            _traceback: object,
        ) -> None:
            raise exc_value

        def close(self) -> None:
            return None

    compiler_module._cleanup_sync_generator(
        provider_gen=_GenBaseIdentity(),
        exc_type=ValueError,
        exc_value=ValueError("same"),
        traceback=None,
    )


def test_cleanup_sync_generator_error_and_invalid_kind_branches() -> None:
    class _GenBaseDifferent:
        def throw(
            self,
            _exc_type: type[BaseException] | None,
            _exc_value: BaseException,
            _traceback: object,
        ) -> None:
            raise KeyError("different")

        def close(self) -> None:
            return None

    with pytest.raises(KeyError, match="different"):
        compiler_module._cleanup_sync_generator(
            provider_gen=_GenBaseDifferent(),
            exc_type=ValueError,
            exc_value=ValueError("value"),
            traceback=None,
        )

    class _GenRuntimeDifferent:
        def throw(
            self,
            _exc_type: type[BaseException] | None,
            _exc_value: BaseException,
            _traceback: object,
        ) -> None:
            raise RuntimeError("boom")

        def close(self) -> None:
            return None

    with pytest.raises(RuntimeError, match="boom"):
        compiler_module._cleanup_sync_generator(
            provider_gen=_GenRuntimeDifferent(),
            exc_type=ValueError,
            exc_value=ValueError("value"),
            traceback=None,
        )

    class _GenNoStop:
        def __init__(self) -> None:
            self.closed = False

        def throw(
            self,
            _exc_type: type[BaseException] | None,
            _exc_value: BaseException,
            _traceback: object,
        ) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    non_stopping = _GenNoStop()
    with pytest.raises(RuntimeError, match="generator didn't stop after throw"):
        compiler_module._cleanup_sync_generator(
            provider_gen=non_stopping,
            exc_type=ValueError,
            exc_value=ValueError("value"),
            traceback=None,
        )
    assert non_stopping.closed is True

    with pytest.raises(
        DIWireAsyncDependencyInSyncContextError,
        match="Cannot execute async cleanup in sync context",
    ):
        compiler_module._execute_sync_cleanup_callback(
            cleanup_kind=99,
            cleanup=lambda *_args: None,
            exc_type=None,
            exc_value=None,
            traceback=None,
        )


@pytest.mark.asyncio
async def test_execute_async_cleanup_callback_generator_fallback_branch() -> None:
    class _GenStop:
        def throw(
            self,
            _exc_type: type[BaseException] | None,
            _exc_value: BaseException,
            _traceback: object,
        ) -> None:
            raise StopIteration

        def close(self) -> None:
            return None

    await compiler_module._execute_async_cleanup_callback(
        cleanup_kind=99,
        cleanup=_GenStop(),
        exc_type=ValueError,
        exc_value=ValueError("value"),
        traceback=None,
    )


def test_resolver_exit_single_cleanup_fast_and_conversion_branches() -> None:
    sync_events: list[str] = []
    tuple_resolver = SimpleNamespace(
        _cleanup_callbacks=[],
        _cleanup_callback_single=(0, lambda *_args: sync_events.append("tuple-sync")),
        _owned_scope_resolvers=(),
        _active=True,
    )
    compiler_module._resolver_exit(tuple_resolver, None, None, None)
    assert sync_events == ["tuple-sync"]
    assert tuple_resolver._cleanup_callback_single is None
    assert tuple_resolver._active is False

    class _GenClose:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    object_cleanup = _GenClose()
    object_resolver = SimpleNamespace(
        _cleanup_callbacks=[],
        _cleanup_callback_single=object_cleanup,
        _owned_scope_resolvers=(),
        _active=True,
    )
    compiler_module._resolver_exit(object_resolver, None, None, None)
    assert object_cleanup.closed is True
    assert object_resolver._cleanup_callback_single is None
    assert object_resolver._active is False

    tuple_generator_cleanup = _GenClose()
    tuple_generator_resolver = SimpleNamespace(
        _cleanup_callbacks=[],
        _cleanup_callback_single=(2, tuple_generator_cleanup),
        _owned_scope_resolvers=(),
        _active=True,
    )
    compiler_module._resolver_exit(tuple_generator_resolver, None, None, None)
    assert tuple_generator_cleanup.closed is True

    converted_cleanup = _GenClose()
    converted_resolver = SimpleNamespace(
        _cleanup_callbacks=[(0, lambda *_args: sync_events.append("list-sync"))],
        _cleanup_callback_single=converted_cleanup,
        _owned_scope_resolvers=(),
        _active=True,
    )
    compiler_module._resolver_exit(converted_resolver, None, None, None)
    assert converted_cleanup.closed is True
    converted_tuple_cleanup = _GenClose()
    converted_tuple_resolver = SimpleNamespace(
        _cleanup_callbacks=[(0, lambda *_args: sync_events.append("tuple-list-sync"))],
        _cleanup_callback_single=(2, converted_tuple_cleanup),
        _owned_scope_resolvers=(),
        _active=True,
    )
    compiler_module._resolver_exit(converted_tuple_resolver, None, None, None)
    assert converted_tuple_cleanup.closed is True
    assert sync_events == ["tuple-sync", "list-sync", "tuple-list-sync"]


@pytest.mark.asyncio
async def test_resolver_aexit_single_cleanup_and_conversion_branches() -> None:
    async_events: list[str] = []

    async def _async_cleanup(*_args: object) -> None:
        async_events.append("tuple-async")

    tuple_async_resolver = SimpleNamespace(
        _cleanup_callbacks=[],
        _cleanup_callback_single=(1, _async_cleanup),
        _owned_scope_resolvers=(),
        _active=True,
    )
    await compiler_module._resolver_aexit(tuple_async_resolver, None, None, None)
    assert async_events == ["tuple-async"]
    assert tuple_async_resolver._cleanup_callback_single is None
    assert tuple_async_resolver._active is False

    tuple_sync_resolver = SimpleNamespace(
        _cleanup_callbacks=[],
        _cleanup_callback_single=(0, lambda *_args: async_events.append("tuple-sync")),
        _owned_scope_resolvers=(),
        _active=True,
    )
    await compiler_module._resolver_aexit(tuple_sync_resolver, None, None, None)

    class _GenClose:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    tuple_generator_cleanup = _GenClose()
    tuple_generator_resolver = SimpleNamespace(
        _cleanup_callbacks=[],
        _cleanup_callback_single=(2, tuple_generator_cleanup),
        _owned_scope_resolvers=(),
        _active=True,
    )
    await compiler_module._resolver_aexit(tuple_generator_resolver, None, None, None)
    assert tuple_generator_cleanup.closed is True

    object_cleanup = _GenClose()
    object_resolver = SimpleNamespace(
        _cleanup_callbacks=[],
        _cleanup_callback_single=object_cleanup,
        _owned_scope_resolvers=(),
        _active=True,
    )
    await compiler_module._resolver_aexit(object_resolver, None, None, None)
    assert object_cleanup.closed is True
    assert object_resolver._cleanup_callback_single is None
    assert object_resolver._active is False

    converted_cleanup = _GenClose()
    converted_resolver = SimpleNamespace(
        _cleanup_callbacks=[(0, lambda *_args: async_events.append("list-sync"))],
        _cleanup_callback_single=converted_cleanup,
        _owned_scope_resolvers=(),
        _active=True,
    )
    await compiler_module._resolver_aexit(converted_resolver, None, None, None)
    assert converted_cleanup.closed is True
    converted_tuple_cleanup = _GenClose()
    converted_tuple_resolver = SimpleNamespace(
        _cleanup_callbacks=[(0, lambda *_args: async_events.append("tuple-list-sync"))],
        _cleanup_callback_single=(2, converted_tuple_cleanup),
        _owned_scope_resolvers=(),
        _active=True,
    )
    await compiler_module._resolver_aexit(converted_tuple_resolver, None, None, None)
    assert converted_tuple_cleanup.closed is True
    assert async_events == ["tuple-async", "tuple-sync", "list-sync", "tuple-list-sync"]

    one_sync_resolver = SimpleNamespace(
        _cleanup_callbacks=[(0, lambda *_args: async_events.append("single-sync"))],
        _cleanup_callback_single=None,
        _owned_scope_resolvers=(),
        _active=True,
    )
    await compiler_module._resolver_aexit(one_sync_resolver, None, None, None)

    one_gen = _GenClose()
    one_generator_resolver = SimpleNamespace(
        _cleanup_callbacks=[(2, one_gen)],
        _cleanup_callback_single=None,
        _owned_scope_resolvers=(),
        _active=True,
    )
    await compiler_module._resolver_aexit(one_generator_resolver, None, None, None)
    assert one_gen.closed is True
    assert async_events[-1] == "single-sync"


def test_resolver_exit_fast_paths_clear_state_on_cleanup_error() -> None:
    class _FailClose:
        def close(self) -> None:
            msg = "close boom"
            raise RuntimeError(msg)

    resolver_single = SimpleNamespace(
        _cleanup_callbacks=[],
        _cleanup_callback_single=_FailClose(),
        _owned_scope_resolvers=(),
        _active=True,
    )
    with pytest.raises(RuntimeError, match="close boom"):
        compiler_module._resolver_exit(resolver_single, None, None, None)
    assert resolver_single._cleanup_callback_single is None
    assert resolver_single._active is False

    resolver_callback = SimpleNamespace(
        _cleanup_callbacks=[(2, _FailClose())],
        _cleanup_callback_single=None,
        _owned_scope_resolvers=(),
        _active=True,
    )
    with pytest.raises(RuntimeError, match="close boom"):
        compiler_module._resolver_exit(resolver_callback, None, None, None)
    assert resolver_callback._active is False


@pytest.mark.asyncio
async def test_resolver_aexit_fast_paths_clear_state_on_cleanup_error() -> None:
    class _FailClose:
        def close(self) -> None:
            msg = "close boom"
            raise RuntimeError(msg)

    resolver_single = SimpleNamespace(
        _cleanup_callbacks=[],
        _cleanup_callback_single=_FailClose(),
        _owned_scope_resolvers=(),
        _active=True,
    )
    with pytest.raises(RuntimeError, match="close boom"):
        await compiler_module._resolver_aexit(resolver_single, None, None, None)
    assert resolver_single._cleanup_callback_single is None
    assert resolver_single._active is False

    resolver_callback = SimpleNamespace(
        _cleanup_callbacks=[(2, _FailClose())],
        _cleanup_callback_single=None,
        _owned_scope_resolvers=(),
        _active=True,
    )
    with pytest.raises(RuntimeError, match="close boom"):
        await compiler_module._resolver_aexit(resolver_callback, None, None, None)
    assert resolver_callback._active is False


def test_generated_exit_fast_path_clears_state_on_close_error() -> None:
    class _Resource:
        pass

    def _provider() -> Any:
        try:
            yield _Resource()
        finally:
            pass

    class _FailClose:
        def close(self) -> None:
            msg = "close boom"
            raise RuntimeError(msg)

    container = Container(use_resolver_context=False)
    container.add_generator(
        _provider,
        provides=_Resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    root_resolver = container.compile()
    request_scope = root_resolver.enter_scope()
    request_scope_any = cast("Any", request_scope)
    request_scope_any._cleanup_callbacks = []
    request_scope_any._cleanup_callback_single = _FailClose()
    request_scope_any._owned_scope_resolvers = ()
    request_scope_any._active = True

    with pytest.raises(RuntimeError, match="close boom"):
        request_scope.__exit__(None, None, None)

    assert request_scope_any._cleanup_callback_single is None
    assert request_scope_any._active is False


def test_execute_fast_single_cleanup_sync_raises_for_async_cleanup_kind() -> None:
    async def _async_cleanup(*_args: object) -> None:
        return None

    resolver = SimpleNamespace(
        _cleanup_callback_single=(compiler_module._CLEANUP_KIND_ASYNC, _async_cleanup),
        _active=True,
    )

    with pytest.raises(
        DIWireAsyncDependencyInSyncContextError,
        match="Cannot execute async cleanup in sync context",
    ):
        compiler_module._execute_fast_single_cleanup_sync(
            self=resolver,
            single_cleanup=resolver._cleanup_callback_single,
        )

    assert resolver._cleanup_callback_single is None
    assert resolver._active is False


def test_execute_fast_single_cleanup_sync_tuple_unknown_kind_falls_back_to_close() -> None:
    class _CloseTracker:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    cleanup = _CloseTracker()
    resolver = SimpleNamespace(
        _cleanup_callback_single=(99, cleanup),
        _active=True,
    )

    compiler_module._execute_fast_single_cleanup_sync(
        self=resolver,
        single_cleanup=resolver._cleanup_callback_single,
    )

    assert cleanup.closed is True
    assert resolver._cleanup_callback_single is None
    assert resolver._active is False


@pytest.mark.asyncio
async def test_generator_cleanup_enabled_branches_raise_when_generator_does_not_yield() -> None:
    dependency = _dependency(name="value")
    dependency_plan = ProviderDependencyPlan(
        kind="literal",
        dependency=dependency,
        dependency_index=0,
        literal_expression="None",
    )

    def _empty_generator(_value: Any = None) -> Any:
        yield from ()

    workflow_with_args = _workflow_plan(
        slot=90,
        provider_attribute="generator",
        is_cached=False,
        dependencies=(dependency,),
        dependency_plans=(dependency_plan,),
        dependency_slots=(None,),
        dependency_requires_async=(False,),
    )
    runtime = _runtime(
        scopes=(_scope_plan(level=1, name="app"),),
        workflows=(workflow_with_args,),
        provider_by_slot={90: _empty_generator},
    )
    scope_resolver = SimpleNamespace(_cleanup_callbacks=[])
    resolver = SimpleNamespace(_cleanup_enabled=True)

    with pytest.raises(RuntimeError, match="generator didn't yield"):
        compiler_module._build_local_value_sync(
            runtime=runtime,
            resolver=resolver,
            workflow=workflow_with_args,
            provider_scope_resolver=scope_resolver,
        )

    with pytest.raises(RuntimeError, match="generator didn't yield"):
        await compiler_module._build_local_value_async(
            runtime=runtime,
            resolver=resolver,
            workflow=workflow_with_args,
            provider_scope_resolver=scope_resolver,
        )

    workflow_no_args = _workflow_plan(
        slot=91,
        provider_attribute="generator",
        is_cached=False,
    )
    with pytest.raises(RuntimeError, match="generator didn't yield"):
        compiler_module._build_local_value_sync_no_arguments(
            resolver=resolver,
            workflow=workflow_no_args,
            provider_scope_resolver=scope_resolver,
            provider=_empty_generator,
        )

    with pytest.raises(RuntimeError, match="generator didn't yield"):
        await compiler_module._build_local_value_async_no_arguments(
            resolver=resolver,
            workflow=workflow_no_args,
            provider_scope_resolver=scope_resolver,
            provider=_empty_generator,
        )
