from __future__ import annotations

import asyncio
import inspect
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

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
    return compiler_module._ResolverRuntime(
        plan=plan,
        ordered_scopes=scopes,
        scopes_by_level={scope.scope_level: scope for scope in scopes},
        workflows_by_slot={workflow.slot: workflow for workflow in workflows},
        class_by_level={},
        root_scope=scopes[0],
        root_scope_level=scopes[0].scope_level,
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

    runtime = compiler._bootstrap_runtime(plan=plan, registrations=registrations)
    assert runtime.context_key_by_name == {}


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
            dependency_requires_async=False,
        )
        == "root"
    )
    assert (
        compiler_module._dependency_value_for_slot_sync(
            runtime=runtime,
            resolver=resolver,
            dependency_workflow=workflow_request,
            dependency_requires_async=True,
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
    )
    assert key in runtime.dep_registered_keys


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
            dependency_requires_async=False,
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
