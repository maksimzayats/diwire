from __future__ import annotations

# ruff: noqa: C901,FBT001,PERF203,PERF401,PLR0911,PLR0912,PLR0913,PLW0108,SLF001,TRY301
import ast
import asyncio
import inspect
import keyword
import logging
import threading
import types
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from types import CodeType, TracebackType
from typing import Any, Final, Literal, cast

from diwire._internal.injection import INJECT_CONTEXT_KWARG, INJECT_RESOLVER_KWARG
from diwire._internal.lock_mode import LockMode
from diwire._internal.markers import (
    component_base_key,
    is_all_annotation,
    is_async_provider_annotation,
    is_from_context_annotation,
    is_maybe_annotation,
    is_provider_annotation,
    strip_all_annotation,
    strip_from_context_annotation,
    strip_maybe_annotation,
    strip_provider_annotation,
)
from diwire._internal.providers import ProviderDependency, ProvidersRegistrations
from diwire._internal.resolvers.assembly.planner import (
    ProviderDependencyPlan,
    ProviderWorkflowPlan,
    ResolverGenerationPlan,
    ResolverGenerationPlanner,
    ScopePlan,
    validate_resolver_assembly_managed_scopes,
)
from diwire._internal.resolvers.protocol import ResolverProtocol
from diwire._internal.scope import BaseScope
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireDependencyNotRegisteredError,
    DIWireScopeMismatchError,
)

logger = logging.getLogger(__name__)

_MISSING_RESOLVER: Final[Any] = object()
_MISSING_CACHE: Final[Any] = object()
_MISSING_DEP_SLOT: Final[Any] = object()
_FALLBACK_ARGUMENT_EXPRESSION: Final[Any] = object()
_OMIT_ARGUMENT: Final[Any] = object()
_FILENAME: Final[str] = "<diwire-resolver>"
_DISPATCH_CACHE_WORKFLOW_THRESHOLD: Final[int] = 4
_INLINE_PROVIDER_EXPRESSION_MAX_DEPTH: Final[int] = 16


@dataclass(frozen=True, slots=True)
class _ArgumentPart:
    kind: Literal["arg", "kw", "star", "starstar"]
    value: Any
    name: str | None = None


@dataclass(slots=True)
class _ResolverRuntime:
    plan: ResolverGenerationPlan
    ordered_scopes: tuple[ScopePlan, ...]
    scopes_by_level: dict[int, ScopePlan]
    workflows_by_slot: dict[int, ProviderWorkflowPlan]
    class_by_level: dict[int, type[Any]]
    root_scope: ScopePlan
    root_scope_level: int
    scope_obj_by_level: dict[int, Any]
    scope_level_by_scope_id: dict[int, int]
    uses_stateless_scope_reuse: bool
    has_cleanup: bool
    dep_registered_keys: set[Any]
    all_slots_by_key: dict[Any, tuple[int, ...]]
    dep_eq_slot_by_key: dict[Any, int]
    dep_type_by_slot: dict[int, Any]
    provider_by_slot: dict[int, Any]
    context_key_by_name: dict[str, Any]
    thread_lock_by_slot: dict[int, threading.Lock]
    async_lock_by_slot: dict[int, asyncio.Lock]
    cache_slots_by_owner_level: dict[int, tuple[int, ...]]
    next_scope_options_by_level: dict[
        int, tuple[ScopePlan | None, ScopePlan | None, tuple[ScopePlan, ...]]
    ]


class ResolversAssemblyCompiler:
    """Compile runtime resolvers with ``type()`` and AST-compiled methods."""

    def build_root_resolver(
        self,
        *,
        root_scope: BaseScope,
        registrations: ProvidersRegistrations,
        cleanup_enabled: bool = True,
    ) -> ResolverProtocol:
        plan = ResolverGenerationPlanner(
            root_scope=root_scope,
            registrations=registrations,
        ).build()
        self._log_plan_strategy(plan=plan)

        runtime = self._bootstrap_runtime(
            plan=plan,
            registrations=registrations,
            root_scope=root_scope,
        )
        generated_globals = self._build_generated_globals(runtime=runtime)

        classes_by_level = self._build_classes(runtime=runtime, generated_globals=generated_globals)
        runtime.class_by_level = classes_by_level

        for scope in runtime.ordered_scopes:
            resolver_class = runtime.class_by_level[scope.scope_level]
            resolver_class._runtime = runtime  # type: ignore[attr-defined]
            resolver_class._class_plan = scope  # type: ignore[attr-defined]

        root_class = runtime.class_by_level[runtime.root_scope_level]
        if runtime.has_cleanup:
            root_resolver = root_class(cleanup_enabled, None, None)
        else:
            root_resolver = root_class(None, None)
        return cast("ResolverProtocol", root_resolver)

    def _log_plan_strategy(self, *, plan: ResolverGenerationPlan) -> None:
        effective_mode_counts = dict(plan.effective_mode_counts)
        logger.info(
            (
                "Resolver assembly strategy: graph_has_async_specs=%s provider_count=%d "
                "cached_provider_count=%d mode_counts={thread:%d,async:%d,none:%d} "
                "thread_lock_count=%d async_lock_count=%d"
            ),
            plan.has_async_specs,
            plan.provider_count,
            plan.cached_provider_count,
            effective_mode_counts.get(LockMode.THREAD, 0),
            effective_mode_counts.get(LockMode.ASYNC, 0),
            effective_mode_counts.get(LockMode.NONE, 0),
            plan.thread_lock_count,
            plan.async_lock_count,
        )

    def _bootstrap_runtime(
        self,
        *,
        plan: ResolverGenerationPlan,
        registrations: ProvidersRegistrations,
        root_scope: BaseScope,
    ) -> _ResolverRuntime:
        ordered_scopes = tuple(sorted(plan.scopes, key=lambda scope: scope.scope_level))
        scopes_by_level = {scope.scope_level: scope for scope in ordered_scopes}
        root_scope_plan = ordered_scopes[0]
        workflows_by_slot = {workflow.slot: workflow for workflow in plan.workflows}

        dep_registered_keys: set[Any] = set()
        all_slots_by_key_mut: dict[Any, list[int]] = {}
        dep_eq_slot_by_key: dict[Any, int] = {}
        dep_type_by_slot: dict[int, Any] = {}
        provider_by_slot: dict[int, Any] = {}
        context_key_by_name: dict[str, Any] = {}

        for workflow in plan.workflows:
            registration = registrations.get_by_slot(workflow.slot)
            dep_type = registration.provides
            dep_type_by_slot[workflow.slot] = dep_type
            provider_by_slot[workflow.slot] = getattr(registration, workflow.provider_attribute)
            dep_registered_keys.add(dep_type)

            base_key = component_base_key(dep_type)
            if base_key is None and not hasattr(dep_type, "__metadata__"):
                base_key = dep_type
            if base_key is not None:
                all_slots_by_key_mut.setdefault(base_key, []).append(workflow.slot)

            if workflow.dispatch_kind == "equality_map":
                dep_eq_slot_by_key[dep_type] = workflow.slot

            for dependency_plan in _dependency_plans_for_workflow(workflow=workflow):
                if dependency_plan.kind != "context":
                    continue
                context_key_name = dependency_plan.ctx_key_global_name
                if context_key_name is None:
                    continue
                context_key_by_name[context_key_name] = strip_from_context_annotation(
                    strip_maybe_annotation(
                        registration.dependencies[dependency_plan.dependency_index].provides,
                    ),
                )

        all_slots_by_key = {key: tuple(slots) for key, slots in all_slots_by_key_mut.items()}

        thread_lock_by_slot = {
            workflow.slot: threading.Lock()
            for workflow in plan.workflows
            if workflow.uses_thread_lock
        }
        async_lock_by_slot = {
            workflow.slot: asyncio.Lock() for workflow in plan.workflows if workflow.uses_async_lock
        }

        cache_slots_by_owner_level_mut: dict[int, list[int]] = {}
        for workflow in plan.workflows:
            owner_level = workflow.cache_owner_scope_level
            if workflow.is_cached and owner_level is not None:
                cache_slots_by_owner_level_mut.setdefault(owner_level, []).append(workflow.slot)

        cache_slots_by_owner_level = {
            level: tuple(sorted(slots)) for level, slots in cache_slots_by_owner_level_mut.items()
        }

        next_scope_options_by_level: dict[
            int,
            tuple[ScopePlan | None, ScopePlan | None, tuple[ScopePlan, ...]],
        ] = {}
        for scope in ordered_scopes:
            deeper_scopes = tuple(
                candidate
                for candidate in ordered_scopes
                if candidate.scope_level > scope.scope_level
            )
            if not deeper_scopes:
                next_scope_options_by_level[scope.scope_level] = (None, None, ())
                continue
            immediate_next = deeper_scopes[0]
            default_next = next(
                (candidate for candidate in deeper_scopes if not candidate.skippable),
                immediate_next,
            )
            next_scope_options_by_level[scope.scope_level] = (
                immediate_next,
                default_next,
                deeper_scopes,
            )

        uses_stateless_scope_reuse = not any(
            workflow.scope_level > plan.root_scope_level for workflow in plan.workflows
        )
        scope_obj_by_level = {
            scope.level: scope
            for scope in validate_resolver_assembly_managed_scopes(root_scope=root_scope)
        }
        scope_level_by_scope_id = {id(scope): level for level, scope in scope_obj_by_level.items()}

        return _ResolverRuntime(
            plan=plan,
            ordered_scopes=ordered_scopes,
            scopes_by_level=scopes_by_level,
            workflows_by_slot=workflows_by_slot,
            class_by_level={},
            root_scope=root_scope_plan,
            root_scope_level=plan.root_scope_level,
            scope_obj_by_level=scope_obj_by_level,
            scope_level_by_scope_id=scope_level_by_scope_id,
            uses_stateless_scope_reuse=uses_stateless_scope_reuse,
            has_cleanup=plan.has_cleanup,
            dep_registered_keys=dep_registered_keys,
            all_slots_by_key=all_slots_by_key,
            dep_eq_slot_by_key=dep_eq_slot_by_key,
            dep_type_by_slot=dep_type_by_slot,
            provider_by_slot=provider_by_slot,
            context_key_by_name=context_key_by_name,
            thread_lock_by_slot=thread_lock_by_slot,
            async_lock_by_slot=async_lock_by_slot,
            cache_slots_by_owner_level=cache_slots_by_owner_level,
            next_scope_options_by_level=next_scope_options_by_level,
        )

    def _build_generated_globals(self, *, runtime: _ResolverRuntime) -> dict[str, Any]:
        generated_globals: dict[str, Any] = {
            "Any": Any,
            "inspect": inspect,
            "_MISSING_RESOLVER": _MISSING_RESOLVER,
            "_MISSING_CACHE": _MISSING_CACHE,
            "_MISSING_DEP_SLOT": _MISSING_DEP_SLOT,
            "_resolver_init": _resolver_init,
            "_resolver_enter_scope": _resolver_enter_scope,
            "_resolver_resolve_from_context": _resolver_resolve_from_context,
            "_resolver_is_registered_dependency": _resolver_is_registered_dependency,
            "_resolver_exit": _resolver_exit,
            "_resolver_aexit": _resolver_aexit,
            "_resolve_dispatch_fallback_sync": _resolve_dispatch_fallback_sync,
            "_resolve_dispatch_fallback_async": _resolve_dispatch_fallback_async,
            "_dep_eq_slot_by_key": runtime.dep_eq_slot_by_key,
            "DIWireAsyncDependencyInSyncContextError": DIWireAsyncDependencyInSyncContextError,
            "DIWireDependencyNotRegisteredError": DIWireDependencyNotRegisteredError,
            "DIWireScopeMismatchError": DIWireScopeMismatchError,
            "is_async_provider_annotation": is_async_provider_annotation,
            "is_all_annotation": is_all_annotation,
            "is_from_context_annotation": is_from_context_annotation,
            "is_maybe_annotation": is_maybe_annotation,
            "is_provider_annotation": is_provider_annotation,
            "strip_all_annotation": strip_all_annotation,
            "strip_from_context_annotation": strip_from_context_annotation,
            "strip_maybe_annotation": strip_maybe_annotation,
            "strip_provider_annotation": strip_provider_annotation,
            "TracebackType": TracebackType,
        }

        for workflow in runtime.plan.workflows:
            generated_globals[f"_dep_{workflow.slot}_type"] = runtime.dep_type_by_slot[
                workflow.slot
            ]
            generated_globals[f"_provider_{workflow.slot}"] = runtime.provider_by_slot[
                workflow.slot
            ]
            generated_globals[f"_sync_slot_{workflow.slot}"] = _build_sync_slot_impl(
                workflow=workflow,
            )
            generated_globals[f"_async_slot_{workflow.slot}"] = _build_async_slot_impl(
                workflow=workflow,
            )

        generated_globals.update(
            {f"_scope_obj_{level}": scope for level, scope in runtime.scope_obj_by_level.items()},
        )
        generated_globals.update(runtime.context_key_by_name)

        return generated_globals

    def _build_classes(
        self,
        *,
        runtime: _ResolverRuntime,
        generated_globals: dict[str, Any],
    ) -> dict[int, type[Any]]:
        classes_by_level: dict[int, type[Any]] = {}

        for scope in runtime.ordered_scopes:
            attrs: dict[str, Any] = {
                "__module__": __name__,
                "__slots__": self._class_slots(runtime=runtime, class_plan=scope),
                "_runtime": None,
                "_class_plan": scope,
            }

            attrs["__init__"] = self._compile_init_method(
                runtime=runtime,
                class_plan=scope,
                generated_globals=generated_globals,
            )
            attrs["enter_scope"] = self._compile_enter_scope_method(
                runtime=runtime,
                class_plan=scope,
                generated_globals=generated_globals,
            )
            attrs["resolve"] = self._compile_dispatch_method(
                runtime=runtime,
                class_plan=scope,
                generated_globals=generated_globals,
                is_async=False,
            )
            attrs["aresolve"] = self._compile_dispatch_method(
                runtime=runtime,
                class_plan=scope,
                generated_globals=generated_globals,
                is_async=True,
            )
            attrs["_resolve_from_context"] = self._compile_simple_method(
                name="_resolve_from_context",
                arg_names=("self", "key"),
                body=[
                    ast.Return(
                        value=ast.Call(
                            func=ast.Name(id="_resolver_resolve_from_context", ctx=ast.Load()),
                            args=[
                                ast.Name(id="self", ctx=ast.Load()),
                                ast.Name(id="key", ctx=ast.Load()),
                            ],
                            keywords=[],
                        ),
                    ),
                ],
                generated_globals=generated_globals,
            )
            attrs["_is_registered_dependency"] = self._compile_simple_method(
                name="_is_registered_dependency",
                arg_names=("self", "dependency"),
                body=[
                    ast.Return(
                        value=ast.Call(
                            func=ast.Name(id="_resolver_is_registered_dependency", ctx=ast.Load()),
                            args=[
                                ast.Name(id="self", ctx=ast.Load()),
                                ast.Name(id="dependency", ctx=ast.Load()),
                            ],
                            keywords=[],
                        ),
                    ),
                ],
                generated_globals=generated_globals,
            )
            attrs["__enter__"] = self._compile_simple_method(
                name="__enter__",
                arg_names=("self",),
                body=[ast.Return(value=ast.Name(id="self", ctx=ast.Load()))],
                generated_globals=generated_globals,
            )
            attrs["__aenter__"] = self._compile_simple_method(
                name="__aenter__",
                arg_names=("self",),
                body=[ast.Return(value=ast.Name(id="self", ctx=ast.Load()))],
                generated_globals=generated_globals,
                is_async=True,
            )
            attrs["__exit__"] = self._compile_exit_method(
                runtime=runtime,
                generated_globals=generated_globals,
                is_async=False,
                has_cleanup=runtime.has_cleanup,
            )
            attrs["__aexit__"] = self._compile_exit_method(
                runtime=runtime,
                generated_globals=generated_globals,
                is_async=True,
                has_cleanup=runtime.has_cleanup,
            )
            attrs["close"] = self._compile_close_method(
                generated_globals=generated_globals,
                is_async=False,
            )
            attrs["aclose"] = self._compile_close_method(
                generated_globals=generated_globals,
                is_async=True,
            )

            for workflow in runtime.plan.workflows:
                attrs[f"resolve_{workflow.slot}"] = self._compile_slot_method(
                    runtime=runtime,
                    workflow=workflow,
                    class_plan=scope,
                    generated_globals=generated_globals,
                    is_async=False,
                )
                attrs[f"aresolve_{workflow.slot}"] = self._compile_slot_method(
                    runtime=runtime,
                    workflow=workflow,
                    class_plan=scope,
                    generated_globals=generated_globals,
                    is_async=True,
                )

            resolver_class = type(scope.class_name, (), attrs)
            classes_by_level[scope.scope_level] = resolver_class

        for resolver_class in classes_by_level.values():
            enter_scope_method = resolver_class.enter_scope
            for scope_level, scope_class in classes_by_level.items():
                enter_scope_method.__globals__[f"_scope_ctor_{scope_level}"] = scope_class

        return classes_by_level

    def _class_slots(
        self,
        *,
        runtime: _ResolverRuntime,
        class_plan: ScopePlan,
    ) -> tuple[str, ...]:
        slots: list[str] = [
            "_root_resolver",
            "_context",
            "_parent_context_resolver",
            "_owned_scope_resolvers",
            "_active",
        ]
        if _dispatch_cache_enabled_for_class(plan=runtime.plan, class_plan=class_plan):
            slots.extend(
                (
                    "_last_sync_dependency",
                    "_last_sync_method",
                    "_last_async_dependency",
                    "_last_async_method",
                ),
            )
        if runtime.has_cleanup:
            slots.append("_cleanup_enabled")
        if runtime.has_cleanup:
            slots.append("_cleanup_callbacks")
        if class_plan.is_root:
            slots.append("__dict__")

        slots.extend(
            scope.resolver_attr_name
            for scope in runtime.ordered_scopes
            if (not scope.is_root and scope.scope_level <= class_plan.scope_level)
        )

        if class_plan.is_root and (runtime.uses_stateless_scope_reuse or not runtime.has_cleanup):
            slots.extend(
                f"_scope_resolver_{scope.scope_level}"
                for scope in runtime.ordered_scopes
                if not scope.is_root
            )

        slots.extend(
            f"_cache_{slot}"
            for slot in runtime.cache_slots_by_owner_level.get(class_plan.scope_level, ())
        )

        return tuple(_unique_ordered(slots))

    def _compile_simple_method(
        self,
        *,
        name: str,
        arg_names: tuple[str, ...],
        body: list[ast.stmt],
        generated_globals: Mapping[str, Any],
        is_async: bool = False,
        defaults: tuple[Any, ...] = (),
        kwonly_defaults: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        arguments = ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg=arg_name) for arg_name in arg_names],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[ast.Constant(value=None) for _ in defaults],
        )
        return _compile_function(
            name=name,
            arguments=arguments,
            body=body,
            generated_globals=generated_globals,
            is_async=is_async,
            defaults=defaults,
            kwonly_defaults=kwonly_defaults,
        )

    def _compile_init_method(
        self,
        *,
        runtime: _ResolverRuntime,
        class_plan: ScopePlan,
        generated_globals: Mapping[str, Any],
    ) -> Callable[..., Any]:
        specialized = self._compile_specialized_init_method(
            runtime=runtime,
            class_plan=class_plan,
            generated_globals=generated_globals,
        )
        if specialized is not None:
            return specialized

        arg_names: tuple[str, ...]
        defaults: tuple[Any, ...]
        body: list[ast.stmt]
        if class_plan.is_root:
            arg_names = ("self", "cleanup_enabled", "context", "parent_context_resolver")
            defaults = (True, None, None)
            body = [
                ast.Expr(
                    value=ast.Call(
                        func=ast.Name(id="_resolver_init", ctx=ast.Load()),
                        args=[
                            ast.Name(id="self", ctx=ast.Load()),
                            ast.Constant(value=None),
                            ast.Name(id="cleanup_enabled", ctx=ast.Load()),
                            ast.Name(id="context", ctx=ast.Load()),
                            ast.Name(id="parent_context_resolver", ctx=ast.Load()),
                        ],
                        keywords=[],
                    ),
                ),
            ]
        else:
            arg_names = (
                "self",
                "root_resolver",
                "cleanup_enabled",
                "context",
                "parent_context_resolver",
            )
            defaults = (True, None, None)
            body = [
                ast.Expr(
                    value=ast.Call(
                        func=ast.Name(id="_resolver_init", ctx=ast.Load()),
                        args=[
                            ast.Name(id="self", ctx=ast.Load()),
                            ast.Name(id="root_resolver", ctx=ast.Load()),
                            ast.Name(id="cleanup_enabled", ctx=ast.Load()),
                            ast.Name(id="context", ctx=ast.Load()),
                            ast.Name(id="parent_context_resolver", ctx=ast.Load()),
                        ],
                        keywords=[],
                    ),
                ),
            ]

        arguments = ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg=arg_name) for arg_name in arg_names],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[ast.Constant(value=None) for _ in defaults],
        )
        return _compile_function(
            name="__init__",
            arguments=arguments,
            body=body,
            generated_globals=generated_globals,
            is_async=False,
            defaults=defaults,
        )

    def _compile_specialized_init_method(
        self,
        *,
        runtime: _ResolverRuntime,
        class_plan: ScopePlan,
        generated_globals: Mapping[str, Any],
    ) -> Callable[..., Any] | None:
        non_root_scopes = tuple(scope for scope in runtime.ordered_scopes if not scope.is_root)
        enable_dispatch_cache = _dispatch_cache_enabled_for_class(
            plan=runtime.plan,
            class_plan=class_plan,
        )

        body_lines: list[str] = [
            f"self._root_resolver = {'self' if class_plan.is_root else 'root_resolver'}",
            "self._context = context",
            "self._parent_context_resolver = parent_context_resolver",
            "self._owned_scope_resolvers = ()",
            "self._active = True",
        ]
        if enable_dispatch_cache:
            body_lines.extend(
                [
                    "self._last_sync_dependency = _MISSING_DEP_SLOT",
                    "self._last_sync_method = None",
                    "self._last_async_dependency = _MISSING_DEP_SLOT",
                    "self._last_async_method = None",
                ],
            )
        if runtime.has_cleanup:
            body_lines.append("self._cleanup_enabled = cleanup_enabled")
        if runtime.has_cleanup:
            body_lines.append("self._cleanup_callbacks = []")

        if class_plan.is_root:
            for non_root_scope in non_root_scopes:
                body_lines.append(f"self.{non_root_scope.resolver_attr_name} = _MISSING_RESOLVER")
        else:
            body_lines.extend(
                [
                    (
                        "parent_scope_level = ("
                        "type(parent_context_resolver)._class_plan.scope_level "
                        "if parent_context_resolver is not None else None)"
                    ),
                ],
            )
            for non_root_scope in non_root_scopes:
                if non_root_scope.scope_level > class_plan.scope_level:
                    continue
                if non_root_scope.scope_level == class_plan.scope_level:
                    body_lines.append(f"self.{non_root_scope.resolver_attr_name} = self")
                    continue
                body_lines.extend(
                    [
                        "if parent_scope_level is None:",
                        f"    self.{non_root_scope.resolver_attr_name} = _MISSING_RESOLVER",
                        f"elif parent_scope_level == {runtime.root_scope_level}:",
                        f"    self.{non_root_scope.resolver_attr_name} = _MISSING_RESOLVER",
                        f"elif parent_scope_level == {non_root_scope.scope_level}:",
                        f"    self.{non_root_scope.resolver_attr_name} = parent_context_resolver",
                        "else:",
                        (
                            f"    self.{non_root_scope.resolver_attr_name} = getattr("
                            f"parent_context_resolver, '{non_root_scope.resolver_attr_name}', "
                            "_MISSING_RESOLVER)"
                        ),
                    ],
                )

        for cache_slot in runtime.cache_slots_by_owner_level.get(class_plan.scope_level, ()):
            body_lines.append(f"self._cache_{cache_slot} = _MISSING_CACHE")

        if class_plan.is_root and (runtime.uses_stateless_scope_reuse or not runtime.has_cleanup):
            for non_root_scope in non_root_scopes:
                body_lines.extend(
                    [
                        f"_scope_class = type(self)._runtime.class_by_level[{non_root_scope.scope_level}]",
                        (
                            f"self._scope_resolver_{non_root_scope.scope_level} = _scope_class("
                            + (
                                "self, cleanup_enabled, None, None)"
                                if runtime.has_cleanup
                                else "self, None, None)"
                            )
                        ),
                        f"self._scope_resolver_{non_root_scope.scope_level}._active = False",
                    ],
                )

        if class_plan.is_root:
            return _compile_function_from_source(
                name="__init__",
                arg_names=(
                    ("self", "cleanup_enabled", "context", "parent_context_resolver")
                    if runtime.has_cleanup
                    else ("self", "context", "parent_context_resolver")
                ),
                body_lines=body_lines,
                generated_globals=generated_globals,
                defaults=((True, None, None) if runtime.has_cleanup else (None, None)),
            )

        return _compile_function_from_source(
            name="__init__",
            arg_names=(
                (
                    "self",
                    "root_resolver",
                    "cleanup_enabled",
                    "context",
                    "parent_context_resolver",
                )
                if runtime.has_cleanup
                else ("self", "root_resolver", "context", "parent_context_resolver")
            ),
            body_lines=body_lines,
            generated_globals=generated_globals,
            defaults=((True, None, None) if runtime.has_cleanup else (None, None)),
        )

    def _compile_enter_scope_method(
        self,
        *,
        runtime: _ResolverRuntime,
        class_plan: ScopePlan,
        generated_globals: Mapping[str, Any],
    ) -> Callable[..., Any]:
        specialized = self._compile_specialized_enter_scope_method(
            runtime=runtime,
            class_plan=class_plan,
            generated_globals=generated_globals,
        )
        if specialized is not None:
            return specialized

        arguments = ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="self"), ast.arg(arg="scope"), ast.arg(arg="context")],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[ast.Constant(value=None), ast.Constant(value=None)],
        )
        body = [
            ast.Return(
                value=ast.Call(
                    func=ast.Name(id="_resolver_enter_scope", ctx=ast.Load()),
                    args=[
                        ast.Name(id="self", ctx=ast.Load()),
                        ast.Name(id="scope", ctx=ast.Load()),
                        ast.Name(id="context", ctx=ast.Load()),
                    ],
                    keywords=[],
                ),
            ),
        ]
        return _compile_function(
            name="enter_scope",
            arguments=arguments,
            body=body,
            generated_globals=generated_globals,
            defaults=(None, None),
        )

    def _compile_specialized_enter_scope_method(
        self,
        *,
        runtime: _ResolverRuntime,
        class_plan: ScopePlan,
        generated_globals: Mapping[str, Any],
    ) -> Callable[..., Any] | None:
        _immediate_next, default_next, _explicit_candidates = (
            runtime.next_scope_options_by_level.get(
                class_plan.scope_level,
                (None, None, ()),
            )
        )
        if default_next is None:
            return None

        target_level = default_next.scope_level
        root_resolver_expression = "self" if class_plan.is_root else "self._root_resolver"

        transition_lines: list[str] = []
        if runtime.uses_stateless_scope_reuse:
            transition_lines.extend(
                [
                    "if context is None and self._context is None and self._parent_context_resolver is None:",
                    f"    return self._root_resolver._scope_resolver_{target_level}",
                ],
            )
        elif class_plan.is_root and not runtime.has_cleanup:
            pooled_lines = [
                "if context is None and self._context is None and self._parent_context_resolver is None:",
                f"    _pooled = self._scope_resolver_{target_level}",
                "    if not _pooled._active:",
                "        _pooled._context = None",
                "        _pooled._parent_context_resolver = self",
                "        _pooled._owned_scope_resolvers = ()",
            ]
            for cache_slot in runtime.cache_slots_by_owner_level.get(target_level, ()):
                pooled_lines.append(f"        _pooled._cache_{cache_slot} = _MISSING_CACHE")
            pooled_lines.extend(
                [
                    "        _pooled._active = True",
                    "        return _pooled",
                ],
            )
            transition_lines.extend(pooled_lines)
        transition_lines.extend(
            [
                (
                    (
                        f"return _scope_ctor_{target_level}("
                        + (
                            f"{root_resolver_expression}, self._cleanup_enabled, context, self)"
                            if runtime.has_cleanup
                            else f"{root_resolver_expression}, context, self)"
                        )
                    )
                    if class_plan.is_root
                    else (f"_scope_class = type(self)._runtime.class_by_level[{target_level}]")
                ),
                *(
                    []
                    if class_plan.is_root
                    else [
                        (
                            "return _scope_class("
                            + (
                                f"{root_resolver_expression}, self._cleanup_enabled, context, self)"
                                if runtime.has_cleanup
                                else f"{root_resolver_expression}, context, self)"
                            )
                        ),
                    ]
                ),
            ],
        )

        body_lines = [
            f"if scope is _scope_obj_{target_level} or scope == {target_level}:",
            *[f"    {line}" for line in transition_lines],
            "if scope is None:",
            *[f"    {line}" for line in transition_lines],
            "return _resolver_enter_scope(self, scope, context)",
        ]

        return _compile_function_from_source(
            name="enter_scope",
            arg_names=("self", "scope", "context"),
            body_lines=body_lines,
            generated_globals=generated_globals,
            defaults=(None, None),
        )

    def _compile_dispatch_method(
        self,
        *,
        runtime: _ResolverRuntime,
        class_plan: ScopePlan,
        generated_globals: Mapping[str, Any],
        is_async: bool,
    ) -> Callable[..., Any]:
        method_name = "aresolve" if is_async else "resolve"
        call_prefix = "aresolve" if is_async else "resolve"
        cache_dependency_attr_name = (
            "_last_async_dependency" if is_async else "_last_sync_dependency"
        )
        cache_method_attr_name = "_last_async_method" if is_async else "_last_sync_method"
        dispatch_workflows = _dispatch_workflows(
            plan=runtime.plan,
            class_plan=class_plan,
        )
        enable_dispatch_cache = len(dispatch_workflows) >= _DISPATCH_CACHE_WORKFLOW_THRESHOLD
        identity_workflows = tuple(
            workflow for workflow in dispatch_workflows if workflow.dispatch_kind == "identity"
        )
        equality_workflows = tuple(
            workflow for workflow in dispatch_workflows if workflow.dispatch_kind == "equality_map"
        )

        body: list[ast.stmt] = []
        if enable_dispatch_cache:
            body.extend(
                [
                    ast.If(
                        test=ast.Compare(
                            left=ast.Name(id="dependency", ctx=ast.Load()),
                            ops=[ast.Is()],
                            comparators=[
                                ast.Attribute(
                                    value=ast.Name(id="self", ctx=ast.Load()),
                                    attr=cache_dependency_attr_name,
                                    ctx=ast.Load(),
                                ),
                            ],
                        ),
                        body=[
                            ast.Return(
                                value=(
                                    ast.Await(
                                        value=ast.Call(
                                            func=ast.Attribute(
                                                value=ast.Name(id="self", ctx=ast.Load()),
                                                attr=cache_method_attr_name,
                                                ctx=ast.Load(),
                                            ),
                                            args=[],
                                            keywords=[],
                                        ),
                                    )
                                    if is_async
                                    else ast.Call(
                                        func=ast.Attribute(
                                            value=ast.Name(id="self", ctx=ast.Load()),
                                            attr=cache_method_attr_name,
                                            ctx=ast.Load(),
                                        ),
                                        args=[],
                                        keywords=[],
                                    )
                                ),
                            ),
                        ],
                        orelse=[],
                    ),
                ],
            )

        def _dispatch_return_body(
            *,
            workflow: ProviderWorkflowPlan,
            cache_dependency: ast.expr,
        ) -> list[ast.stmt]:
            slot = workflow.slot

            call_expr = ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr=f"{call_prefix}_{slot}",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            )
            if is_async:
                return_expr: ast.expr = ast.Await(value=call_expr)
            else:
                return_expr = call_expr

            inline_return_expr: ast.expr | None = None
            if (
                not is_async
                and not workflow.requires_async
                and not workflow.provider_is_inject_wrapper
            ):
                if workflow.provider_attribute == "instance":
                    inline_return_expr = ast.Name(id=f"_provider_{slot}", ctx=ast.Load())
                elif (
                    workflow.scope_level == class_plan.scope_level
                    and not workflow.is_cached
                    and workflow.provider_attribute in {"concrete_type", "factory"}
                    and not workflow.dependencies
                    and not workflow.dependency_plans
                ):
                    inline_return_expr = ast.Call(
                        func=ast.Name(id=f"_provider_{slot}", ctx=ast.Load()),
                        args=[],
                        keywords=[],
                    )

            precheck_body: list[ast.stmt] = []
            if (
                workflow.is_cached
                and workflow.cache_owner_scope_level == class_plan.scope_level
                and workflow.cache_owner_scope_level == runtime.root_scope_level
            ):
                precheck_body = [
                    ast.Assign(
                        targets=[ast.Name(id="cached_value", ctx=ast.Store())],
                        value=ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=f"_cache_{slot}",
                            ctx=ast.Load(),
                        ),
                    ),
                    ast.If(
                        test=ast.Compare(
                            left=ast.Name(id="cached_value", ctx=ast.Load()),
                            ops=[ast.IsNot()],
                            comparators=[ast.Name(id="_MISSING_CACHE", ctx=ast.Load())],
                        ),
                        body=[
                            ast.Return(
                                value=ast.Name(id="cached_value", ctx=ast.Load()),
                            ),
                        ],
                        orelse=[],
                    ),
                ]

            if not enable_dispatch_cache or workflow.is_cached:
                resolved_return_expr = inline_return_expr or return_expr
                return [
                    *precheck_body,
                    ast.Return(value=resolved_return_expr),
                ]

            cached_method_call = ast.Call(
                func=ast.Name(id="cached_method", ctx=ast.Load()),
                args=[],
                keywords=[],
            )
            return [
                *precheck_body,
                ast.Assign(
                    targets=[ast.Name(id="cached_method", ctx=ast.Store())],
                    value=ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()),
                        attr=f"{call_prefix}_{workflow.slot}",
                        ctx=ast.Load(),
                    ),
                ),
                ast.Assign(
                    targets=[
                        ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=cache_dependency_attr_name,
                            ctx=ast.Store(),
                        ),
                    ],
                    value=cache_dependency,
                ),
                ast.Assign(
                    targets=[
                        ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=cache_method_attr_name,
                            ctx=ast.Store(),
                        ),
                    ],
                    value=ast.Name(id="cached_method", ctx=ast.Load()),
                ),
                ast.Return(
                    value=ast.Await(value=cached_method_call) if is_async else cached_method_call,
                ),
            ]

        for workflow in identity_workflows:
            body.append(
                ast.If(
                    test=ast.Compare(
                        left=ast.Name(id="dependency", ctx=ast.Load()),
                        ops=[ast.Is()],
                        comparators=[ast.Name(id=f"_dep_{workflow.slot}_type", ctx=ast.Load())],
                    ),
                    body=_dispatch_return_body(
                        workflow=workflow,
                        cache_dependency=ast.Name(
                            id=f"_dep_{workflow.slot}_type",
                            ctx=ast.Load(),
                        ),
                    ),
                    orelse=[],
                ),
            )

        if equality_workflows:
            body.append(
                ast.Assign(
                    targets=[ast.Name(id="slot", ctx=ast.Store())],
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id="_dep_eq_slot_by_key", ctx=ast.Load()),
                            attr="get",
                            ctx=ast.Load(),
                        ),
                        args=[
                            ast.Name(id="dependency", ctx=ast.Load()),
                            ast.Name(id="_MISSING_DEP_SLOT", ctx=ast.Load()),
                        ],
                        keywords=[],
                    ),
                ),
            )

            switch_body: list[ast.If] = []
            for index, workflow in enumerate(equality_workflows):
                compare = ast.Compare(
                    left=ast.Name(id="slot", ctx=ast.Load()),
                    ops=[ast.Eq()],
                    comparators=[ast.Constant(value=workflow.slot)],
                )
                switch_body.append(
                    ast.If(
                        test=compare,
                        body=_dispatch_return_body(
                            workflow=workflow,
                            cache_dependency=ast.Name(id="dependency", ctx=ast.Load()),
                        ),
                        orelse=[],
                    ),
                )
                if index > 0:
                    switch_body[index - 1].orelse = [switch_body[index]]

            body.append(
                ast.If(
                    test=ast.Compare(
                        left=ast.Name(id="slot", ctx=ast.Load()),
                        ops=[ast.IsNot()],
                        comparators=[ast.Name(id="_MISSING_DEP_SLOT", ctx=ast.Load())],
                    ),
                    body=[switch_body[0]],
                    orelse=[],
                ),
            )

        fallback_function = (
            "_resolve_dispatch_fallback_async" if is_async else "_resolve_dispatch_fallback_sync"
        )
        fallback_call = ast.Call(
            func=ast.Name(id=fallback_function, ctx=ast.Load()),
            args=[
                ast.Name(id="self", ctx=ast.Load()),
                ast.Name(id="dependency", ctx=ast.Load()),
            ],
            keywords=[],
        )
        body.append(
            ast.Return(
                value=ast.Await(value=fallback_call) if is_async else fallback_call,
            ),
        )

        arguments = ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="self"), ast.arg(arg="dependency")],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        )
        return _compile_function(
            name=method_name,
            arguments=arguments,
            body=body,
            generated_globals=generated_globals,
            is_async=is_async,
        )

    def _compile_exit_method(
        self,
        *,
        runtime: _ResolverRuntime,
        generated_globals: Mapping[str, Any],
        is_async: bool,
        has_cleanup: bool,
    ) -> Callable[..., Any]:
        name = "__aexit__" if is_async else "__exit__"
        if not has_cleanup:
            return self._compile_no_cleanup_exit_method(
                runtime=runtime,
                generated_globals=generated_globals,
                is_async=is_async,
                name=name,
            )

        function_name = "_resolver_aexit" if is_async else "_resolver_exit"
        arguments = ast.arguments(
            posonlyargs=[],
            args=[
                ast.arg(arg="self"),
                ast.arg(arg="exc_type"),
                ast.arg(arg="exc_value"),
                ast.arg(arg="traceback"),
            ],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        )
        call = ast.Call(
            func=ast.Name(id=function_name, ctx=ast.Load()),
            args=[
                ast.Name(id="self", ctx=ast.Load()),
                ast.Name(id="exc_type", ctx=ast.Load()),
                ast.Name(id="exc_value", ctx=ast.Load()),
                ast.Name(id="traceback", ctx=ast.Load()),
            ],
            keywords=[],
        )
        body = [ast.Return(value=ast.Await(value=call) if is_async else call)]
        return _compile_function(
            name=name,
            arguments=arguments,
            body=body,
            generated_globals=generated_globals,
            is_async=is_async,
        )

    def _compile_no_cleanup_exit_method(
        self,
        *,
        runtime: _ResolverRuntime,
        generated_globals: Mapping[str, Any],
        is_async: bool,
        name: str,
    ) -> Callable[..., Any]:
        if runtime.uses_stateless_scope_reuse:
            body_lines = [
                "return None",
            ]
            return _compile_function_from_source(
                name=name,
                arg_names=("self", "exc_type", "exc_value", "traceback"),
                body_lines=body_lines,
                generated_globals=generated_globals,
                is_async=is_async,
            )

        if is_async:
            body_lines = [
                "if not self._owned_scope_resolvers:",
                "    self._active = False",
                "    return None",
                "for owned_scope_resolver in reversed(self._owned_scope_resolvers):",
                "    await owned_scope_resolver.__aexit__(exc_type, exc_value, traceback)",
                "self._active = False",
                "return None",
            ]
        else:
            body_lines = [
                "if not self._owned_scope_resolvers:",
                "    self._active = False",
                "    return None",
                "for owned_scope_resolver in reversed(self._owned_scope_resolvers):",
                "    owned_scope_resolver.__exit__(exc_type, exc_value, traceback)",
                "self._active = False",
                "return None",
            ]

        return _compile_function_from_source(
            name=name,
            arg_names=("self", "exc_type", "exc_value", "traceback"),
            body_lines=body_lines,
            generated_globals=generated_globals,
            is_async=is_async,
        )

    def _compile_close_method(
        self,
        *,
        generated_globals: Mapping[str, Any],
        is_async: bool,
    ) -> Callable[..., Any]:
        name = "aclose" if is_async else "close"
        delegated_name = "__aexit__" if is_async else "__exit__"
        arguments = ast.arguments(
            posonlyargs=[],
            args=[
                ast.arg(arg="self"),
                ast.arg(arg="exc_type"),
                ast.arg(arg="exc_value"),
                ast.arg(arg="traceback"),
            ],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[ast.Constant(value=None), ast.Constant(value=None), ast.Constant(value=None)],
        )
        delegated_call = ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="self", ctx=ast.Load()),
                attr=delegated_name,
                ctx=ast.Load(),
            ),
            args=[
                ast.Name(id="exc_type", ctx=ast.Load()),
                ast.Name(id="exc_value", ctx=ast.Load()),
                ast.Name(id="traceback", ctx=ast.Load()),
            ],
            keywords=[],
        )
        body = [
            ast.Return(value=ast.Await(value=delegated_call) if is_async else delegated_call),
        ]
        return _compile_function(
            name=name,
            arguments=arguments,
            body=body,
            generated_globals=generated_globals,
            is_async=is_async,
            defaults=(None, None, None),
        )

    def _compile_slot_method(
        self,
        *,
        runtime: _ResolverRuntime,
        workflow: ProviderWorkflowPlan,
        class_plan: ScopePlan,
        generated_globals: Mapping[str, Any],
        is_async: bool,
    ) -> Callable[..., Any]:
        if not is_async:
            specialized_sync = self._compile_specialized_sync_slot_method(
                runtime=runtime,
                workflow=workflow,
                class_plan=class_plan,
                generated_globals=generated_globals,
            )
            if specialized_sync is not None:
                return specialized_sync

        method_name = f"aresolve_{workflow.slot}" if is_async else f"resolve_{workflow.slot}"
        global_name = f"_async_slot_{workflow.slot}" if is_async else f"_sync_slot_{workflow.slot}"
        arguments = ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="self")],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        )
        call = ast.Call(
            func=ast.Name(id=global_name, ctx=ast.Load()),
            args=[ast.Name(id="self", ctx=ast.Load())],
            keywords=[],
        )
        body: list[ast.stmt] = []
        if workflow.is_cached and workflow.cache_owner_scope_level == class_plan.scope_level:
            body.extend(
                [
                    ast.Assign(
                        targets=[ast.Name(id="cached_value", ctx=ast.Store())],
                        value=ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=f"_cache_{workflow.slot}",
                            ctx=ast.Load(),
                        ),
                    ),
                    ast.If(
                        test=ast.Compare(
                            left=ast.Name(id="cached_value", ctx=ast.Load()),
                            ops=[ast.IsNot()],
                            comparators=[ast.Name(id="_MISSING_CACHE", ctx=ast.Load())],
                        ),
                        body=[ast.Return(value=ast.Name(id="cached_value", ctx=ast.Load()))],
                        orelse=[],
                    ),
                ],
            )

        body.append(ast.Return(value=ast.Await(value=call) if is_async else call))
        return _compile_function(
            name=method_name,
            arguments=arguments,
            body=body,
            generated_globals=generated_globals,
            is_async=is_async,
        )

    def _compile_specialized_sync_slot_method(
        self,
        *,
        runtime: _ResolverRuntime,
        workflow: ProviderWorkflowPlan,
        class_plan: ScopePlan,
        generated_globals: Mapping[str, Any],
    ) -> Callable[..., Any] | None:
        if workflow.uses_thread_lock:
            return None
        if workflow.provider_is_inject_wrapper:
            return None

        method_name = f"resolve_{workflow.slot}"
        class_scope_level = class_plan.scope_level
        lines: list[str] = []

        owner_scope_level = workflow.cache_owner_scope_level
        if (
            workflow.is_cached
            and owner_scope_level is not None
            and owner_scope_level != class_scope_level
        ):
            if owner_scope_level > class_scope_level:
                lines.extend(_scope_mismatch_lines_for_source(workflow=workflow))
            else:
                lines.extend(
                    _delegate_scope_lines_for_source(
                        runtime=runtime,
                        workflow=workflow,
                        scope_level=owner_scope_level,
                    ),
                )
            return _compile_function_from_source(
                name=method_name,
                arg_names=("self",),
                body_lines=lines,
                generated_globals=generated_globals,
            )

        if workflow.scope_level > class_scope_level:
            lines.extend(_scope_mismatch_lines_for_source(workflow=workflow))
            return _compile_function_from_source(
                name=method_name,
                arg_names=("self",),
                body_lines=lines,
                generated_globals=generated_globals,
            )

        if (
            workflow.scope_level < class_scope_level
            and workflow.max_required_scope_level <= workflow.scope_level
        ):
            lines.extend(
                _delegate_scope_lines_for_source(
                    runtime=runtime,
                    workflow=workflow,
                    scope_level=workflow.scope_level,
                ),
            )
            return _compile_function_from_source(
                name=method_name,
                arg_names=("self",),
                body_lines=lines,
                generated_globals=generated_globals,
            )

        if workflow.scope_level != class_scope_level:
            return None

        if workflow.requires_async:
            lines.extend(
                [
                    f'msg = "Provider slot {workflow.slot} requires asynchronous resolution."',
                    "raise DIWireAsyncDependencyInSyncContextError(msg)",
                ],
            )
            return _compile_function_from_source(
                name=method_name,
                arg_names=("self",),
                body_lines=lines,
                generated_globals=generated_globals,
            )

        if workflow.provider_attribute not in {"instance", "concrete_type", "factory"}:
            return None

        if workflow.is_cached:
            lines.extend(
                [
                    f"cached_value = self._cache_{workflow.slot}",
                    "if cached_value is not _MISSING_CACHE:",
                    "    return cached_value",
                ],
            )

        value_expression: str
        if workflow.provider_attribute == "instance":
            value_expression = f"_provider_{workflow.slot}"
        else:
            optimized_arguments = self._optimized_sync_arguments(
                runtime=runtime,
                class_plan=class_plan,
                workflow=workflow,
                inline_depth=0,
                seen_slots={workflow.slot},
            )
            arguments = ", ".join(argument for argument in optimized_arguments if argument)
            value_expression = (
                f"_provider_{workflow.slot}({arguments})"
                if arguments
                else f"_provider_{workflow.slot}()"
            )
        lines.append(f"value = {value_expression}")

        if workflow.is_provider_async:
            lines.extend(
                [
                    "if inspect.isawaitable(value):",
                    f'    msg = "Provider slot {workflow.slot} requires asynchronous resolution."',
                    "    raise DIWireAsyncDependencyInSyncContextError(msg)",
                ],
            )

        if workflow.is_cached:
            lines.append(f"self._cache_{workflow.slot} = value")
            if workflow.cache_owner_scope_level == runtime.root_scope_level:
                lines.append(f"self.resolve_{workflow.slot} = lambda: value")

        lines.append("return value")
        return _compile_function_from_source(
            name=method_name,
            arg_names=("self",),
            body_lines=lines,
            generated_globals=generated_globals,
        )

    def _optimized_sync_arguments(
        self,
        *,
        runtime: _ResolverRuntime,
        class_plan: ScopePlan,
        workflow: ProviderWorkflowPlan,
        inline_depth: int,
        seen_slots: set[int],
    ) -> tuple[str, ...]:
        dependency_plans = workflow.dependency_plans
        if not dependency_plans:
            return ()

        resolver_expression = (
            "self" if class_plan.scope_level == runtime.root_scope_level else "self._root_resolver"
        )
        optimized_arguments: list[str] = []
        prefer_positional = workflow.dependency_order_is_signature_order
        skip_positional_only = False

        for dependency_plan in dependency_plans:
            dependency = dependency_plan.dependency
            parameter_kind = dependency.parameter.kind

            if skip_positional_only and parameter_kind is inspect.Parameter.POSITIONAL_ONLY:
                continue

            expression = self._optimized_sync_dependency_expression(
                runtime=runtime,
                class_plan=class_plan,
                dependency_plan=dependency_plan,
                resolver_expression=resolver_expression,
                inline_depth=inline_depth,
                seen_slots=seen_slots,
            )
            if expression is _FALLBACK_ARGUMENT_EXPRESSION:
                return workflow.sync_arguments
            if expression is not None and not isinstance(expression, str):
                return workflow.sync_arguments

            if expression is None or expression == "":
                if parameter_kind in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                }:
                    prefer_positional = False
                if parameter_kind is inspect.Parameter.POSITIONAL_ONLY:
                    skip_positional_only = True
                continue

            if parameter_kind is inspect.Parameter.POSITIONAL_ONLY:
                optimized_arguments.append(expression)
                continue
            if parameter_kind is inspect.Parameter.POSITIONAL_OR_KEYWORD and prefer_positional:
                optimized_arguments.append(expression)
                continue
            if parameter_kind is inspect.Parameter.VAR_POSITIONAL:
                optimized_arguments.append(f"*{expression}")
                continue
            if parameter_kind is inspect.Parameter.VAR_KEYWORD:
                optimized_arguments.append(f"**{expression}")
                continue

            parameter_name = dependency.parameter.name
            if not parameter_name.isidentifier() or keyword.iskeyword(parameter_name):
                return workflow.sync_arguments
            optimized_arguments.append(f"{parameter_name}={expression}")

        if workflow.provider_is_inject_wrapper:
            resolver_kwarg = f"{INJECT_RESOLVER_KWARG}=self"
            for index, argument in enumerate(optimized_arguments):
                if argument.startswith("**"):
                    optimized_arguments.insert(index, resolver_kwarg)
                    break
            else:
                optimized_arguments.append(resolver_kwarg)

        return tuple(optimized_arguments)

    def _optimized_sync_dependency_expression(
        self,
        *,
        runtime: _ResolverRuntime,
        class_plan: ScopePlan,
        dependency_plan: ProviderDependencyPlan,
        resolver_expression: str,
        inline_depth: int,
        seen_slots: set[int],
    ) -> str | None | object:
        if dependency_plan.kind == "omit":
            return None
        if dependency_plan.kind == "literal":
            return dependency_plan.literal_expression
        if dependency_plan.kind == "provider_handle":
            provider_inner_slot = dependency_plan.provider_inner_slot
            if provider_inner_slot is None:
                return _FALLBACK_ARGUMENT_EXPRESSION
            return (
                f"lambda: self.aresolve_{provider_inner_slot}()"
                if dependency_plan.provider_is_async
                else f"lambda: self.resolve_{provider_inner_slot}()"
            )
        if dependency_plan.kind == "context":
            context_key_name = dependency_plan.ctx_key_global_name
            if context_key_name is None:
                return _FALLBACK_ARGUMENT_EXPRESSION
            return f"self._resolve_from_context({context_key_name})"
        if dependency_plan.kind == "all":
            slots = dependency_plan.all_slots
            if not slots:
                return "()"
            if len(slots) == 1:
                return f"(self.resolve_{slots[0]}(),)"
            return "(" + ", ".join(f"self.resolve_{slot}()" for slot in slots) + ")"

        dependency_slot = dependency_plan.dependency_slot
        if dependency_slot is None:
            return _FALLBACK_ARGUMENT_EXPRESSION
        dependency_workflow = runtime.workflows_by_slot[dependency_slot]
        expression = f"self.resolve_{dependency_slot}()"
        if (
            class_plan.scope_level > dependency_workflow.scope_level
            and dependency_workflow.max_required_scope_level <= dependency_workflow.scope_level
        ):
            if dependency_workflow.scope_level == runtime.root_scope_level:
                expression = f"self._root_resolver.resolve_{dependency_slot}()"
            else:
                owner_scope = runtime.scopes_by_level[dependency_workflow.scope_level]
                expression = f"self.{owner_scope.resolver_attr_name}.resolve_{dependency_slot}()"

        if (
            dependency_workflow.is_cached
            and dependency_workflow.cache_owner_scope_level == runtime.root_scope_level
        ):
            expression = (
                f"({resolver_expression}._cache_{dependency_slot} if "
                f"{resolver_expression}._cache_{dependency_slot} is not _MISSING_CACHE else "
                f"{resolver_expression}.resolve_{dependency_slot}())"
            )

        if self._is_safe_to_inline_sync_provider_call(
            class_plan=class_plan,
            workflow=dependency_workflow,
            slot=dependency_slot,
            inline_depth=inline_depth,
            seen_slots=seen_slots,
        ):
            seen_slots.add(dependency_slot)
            try:
                if dependency_workflow.provider_attribute == "instance":
                    return f"_provider_{dependency_slot}"
                optimized_arguments = self._optimized_sync_arguments(
                    runtime=runtime,
                    class_plan=class_plan,
                    workflow=dependency_workflow,
                    inline_depth=inline_depth + 1,
                    seen_slots=seen_slots,
                )
                arguments = ", ".join(argument for argument in optimized_arguments if argument)
                return (
                    f"_provider_{dependency_slot}({arguments})"
                    if arguments
                    else f"_provider_{dependency_slot}()"
                )
            finally:
                seen_slots.remove(dependency_slot)

        return expression

    def _is_safe_to_inline_sync_provider_call(
        self,
        *,
        class_plan: ScopePlan,
        workflow: ProviderWorkflowPlan,
        slot: int,
        inline_depth: int,
        seen_slots: set[int],
    ) -> bool:
        if inline_depth >= _INLINE_PROVIDER_EXPRESSION_MAX_DEPTH:
            return False
        if slot in seen_slots:
            return False
        if workflow.scope_level != class_plan.scope_level:
            return False
        if workflow.max_required_scope_level > workflow.scope_level:
            return False
        if workflow.is_cached or not workflow.is_transient:
            return False
        if workflow.requires_async or workflow.is_provider_async:
            return False
        if workflow.uses_thread_lock or workflow.uses_async_lock:
            return False
        if workflow.provider_is_inject_wrapper or workflow.needs_cleanup:
            return False
        return workflow.provider_attribute in {"instance", "concrete_type", "factory"}


def _compile_function(
    *,
    name: str,
    arguments: ast.arguments,
    body: Sequence[ast.stmt],
    generated_globals: Mapping[str, Any],
    is_async: bool = False,
    defaults: tuple[Any, ...] = (),
    kwonly_defaults: dict[str, Any] | None = None,
) -> Callable[..., Any]:
    function_definition: ast.FunctionDef | ast.AsyncFunctionDef
    if is_async:
        function_definition = ast.AsyncFunctionDef(
            name=name,
            args=arguments,
            body=list(body),
            decorator_list=[],
            returns=None,
            type_comment=None,
        )
    else:
        function_definition = ast.FunctionDef(
            name=name,
            args=arguments,
            body=list(body),
            decorator_list=[],
            returns=None,
            type_comment=None,
        )

    module = ast.Module(body=[function_definition], type_ignores=[])
    ast.fix_missing_locations(module)
    module_code = compile(module, filename=_FILENAME, mode="exec")
    function_code = _extract_function_code(module_code=module_code, name=name)
    function = types.FunctionType(function_code, dict(generated_globals), name=name)
    if defaults:
        function.__defaults__ = defaults
    if kwonly_defaults is not None:
        function.__kwdefaults__ = kwonly_defaults
    return function


def _compile_function_from_source(
    *,
    name: str,
    arg_names: tuple[str, ...],
    kwonly_arg_names: tuple[str, ...] = (),
    body_lines: Sequence[str],
    generated_globals: Mapping[str, Any],
    is_async: bool = False,
    defaults: tuple[Any, ...] = (),
    kwonly_defaults: dict[str, Any] | None = None,
) -> Callable[..., Any]:
    signature_parts = [", ".join(arg_names)] if arg_names else []
    if kwonly_arg_names:
        signature_parts.append("*")
        signature_parts.extend(kwonly_arg_names)
    signature = ", ".join(part for part in signature_parts if part)
    function_keyword = "async def" if is_async else "def"
    rendered_body = "\n".join(f"    {line}" for line in body_lines) if body_lines else "    pass"
    source = f"{function_keyword} {name}({signature}):\n{rendered_body}\n"
    module_code = compile(source, filename=_FILENAME, mode="exec")
    function_code = _extract_function_code(module_code=module_code, name=name)
    function = types.FunctionType(function_code, dict(generated_globals), name=name)
    if defaults:
        function.__defaults__ = defaults
    if kwonly_defaults is not None:
        function.__kwdefaults__ = kwonly_defaults
    return function


def _extract_function_code(*, module_code: CodeType, name: str) -> CodeType:
    stack = [module_code]
    while stack:
        current = stack.pop()
        for constant in current.co_consts:
            if isinstance(constant, CodeType):
                if constant.co_name == name:
                    return constant
                stack.append(constant)
    msg = f"Unable to extract function code object for {name!r}."
    raise RuntimeError(msg)


def _scope_mismatch_lines_for_source(*, workflow: ProviderWorkflowPlan) -> list[str]:
    return [
        f'msg = "Provider slot {workflow.slot} requires opened scope level {workflow.scope_level}."',
        "raise DIWireScopeMismatchError(msg)",
    ]


def _delegate_scope_lines_for_source(
    *,
    runtime: _ResolverRuntime,
    workflow: ProviderWorkflowPlan,
    scope_level: int,
) -> list[str]:
    scope = runtime.scopes_by_level[scope_level]
    if scope.is_root:
        return [f"return self.{scope.resolver_attr_name}.resolve_{workflow.slot}()"]

    return [
        f"owner_resolver = self.{scope.resolver_attr_name}",
        "if owner_resolver is _MISSING_RESOLVER:",
        f'    msg = "Provider slot {workflow.slot} requires opened scope level {workflow.scope_level}."',
        "    raise DIWireScopeMismatchError(msg)",
        f"return owner_resolver.resolve_{workflow.slot}()",
    ]


def _resolver_init(
    self: Any,
    root_resolver: Any,
    cleanup_enabled: bool,
    context: Any | None,
    parent_context_resolver: Any,
) -> None:
    runtime = type(self)._runtime
    class_plan = type(self)._class_plan

    if class_plan.is_root:
        self._root_resolver = self
    else:
        self._root_resolver = root_resolver

    self._context = context
    self._parent_context_resolver = parent_context_resolver
    self._active = True
    if hasattr(self, "_last_sync_dependency"):
        self._last_sync_dependency = _MISSING_DEP_SLOT
        self._last_sync_method = None
        self._last_async_dependency = _MISSING_DEP_SLOT
        self._last_async_method = None
    if runtime.has_cleanup:
        self._cleanup_enabled = cleanup_enabled
        self._cleanup_callbacks = []
    self._owned_scope_resolvers = ()

    for scope in runtime.ordered_scopes:
        if scope.is_root:
            continue

        attr_name = scope.resolver_attr_name
        if class_plan.is_root:
            continue

        if scope.scope_level == class_plan.scope_level:
            setattr(self, attr_name, self)
            continue

        if scope.scope_level > class_plan.scope_level:
            continue

        ancestor_resolver = _MISSING_RESOLVER
        if parent_context_resolver is not None:
            parent_scope_level = _resolver_scope_level(parent_context_resolver)
            if parent_scope_level == scope.scope_level:
                ancestor_resolver = parent_context_resolver
            else:
                ancestor_resolver = getattr(
                    parent_context_resolver,
                    attr_name,
                    _MISSING_RESOLVER,
                )
        setattr(self, attr_name, ancestor_resolver)

    for cache_slot in runtime.cache_slots_by_owner_level.get(class_plan.scope_level, ()):
        setattr(self, f"_cache_{cache_slot}", _MISSING_CACHE)

    if class_plan.is_root and (runtime.uses_stateless_scope_reuse or not runtime.has_cleanup):
        for scope in runtime.ordered_scopes:
            if scope.is_root:
                continue
            scope_class = runtime.class_by_level[scope.scope_level]
            if runtime.has_cleanup:
                scope_resolver = scope_class(
                    self,
                    cleanup_enabled,
                    None,
                    None,
                )
            else:
                scope_resolver = scope_class(
                    self,
                    None,
                    None,
                )
            scope_resolver._active = False
            setattr(self, f"_scope_resolver_{scope.scope_level}", scope_resolver)


def _resolver_enter_scope(
    self: Any,
    scope: Any | None,
    context: Mapping[Any, Any] | None,
) -> Any:
    runtime = type(self)._runtime
    class_plan = type(self)._class_plan

    immediate_next, default_next, explicit_candidates = _next_scope_options(
        runtime=runtime,
        class_scope_level=class_plan.scope_level,
    )
    if immediate_next is None or default_next is None:
        msg = f"Cannot enter deeper scope from level {class_plan.scope_level}."
        raise DIWireScopeMismatchError(msg)

    if scope is None:
        return _instantiate_scope_transition(
            runtime=runtime,
            current_resolver=self,
            target_scope=default_next,
            context=context,
        )

    default_scope_obj = runtime.scope_obj_by_level.get(default_next.scope_level)
    if scope is default_scope_obj or scope == default_next.scope_level:
        return _instantiate_scope_transition(
            runtime=runtime,
            current_resolver=self,
            target_scope=default_next,
            context=context,
        )

    target_scope_level = runtime.scope_level_by_scope_id.get(id(scope), scope)

    if target_scope_level is class_plan.scope_level or target_scope_level == class_plan.scope_level:
        return self

    if target_scope_level <= class_plan.scope_level:
        msg = f"Cannot enter scope level {target_scope_level} from level {class_plan.scope_level}."
        raise DIWireScopeMismatchError(msg)

    explicit_scope_levels = {candidate.scope_level for candidate in explicit_candidates}
    if target_scope_level not in explicit_scope_levels:
        msg = (
            f"Scope level {target_scope_level} is not a valid next transition from level "
            f"{class_plan.scope_level}."
        )
        raise DIWireScopeMismatchError(msg)

    if runtime.uses_stateless_scope_reuse:
        target_level = int(target_scope_level)
        if context is None and self._context is None and self._parent_context_resolver is None:
            return getattr(self._root_resolver, f"_scope_resolver_{target_level}")

        target_class = runtime.class_by_level[target_level]
        if runtime.has_cleanup:
            return target_class(
                self._root_resolver,
                self._cleanup_enabled,
                context,
                self,
            )
        return target_class(
            self._root_resolver,
            context,
            self,
        )

    transition_plan = _build_transition_plan_to_target(
        runtime=runtime,
        class_scope_level=class_plan.scope_level,
        target_scope_level=int(target_scope_level),
    )

    if len(transition_plan) == 1:
        return _instantiate_scope_transition(
            runtime=runtime,
            current_resolver=self,
            target_scope=transition_plan[0],
            context=context,
        )

    root_resolver = self if class_plan.is_root else self._root_resolver
    current_resolver = self
    created_resolvers: list[Any] = []
    cleanup_enabled = getattr(self, "_cleanup_enabled", True)

    for index, scope_plan in enumerate(transition_plan):
        target_class = runtime.class_by_level[scope_plan.scope_level]
        nested_context = context if index == len(transition_plan) - 1 else None
        if runtime.has_cleanup:
            next_resolver = target_class(
                root_resolver,
                cleanup_enabled,
                nested_context,
                current_resolver,
            )
        else:
            next_resolver = target_class(
                root_resolver,
                nested_context,
                current_resolver,
            )
        created_resolvers.append(next_resolver)
        current_resolver = next_resolver

    deepest_resolver = created_resolvers[-1]
    deepest_resolver._owned_scope_resolvers = tuple(created_resolvers[:-1])
    return deepest_resolver


def _instantiate_scope_transition(
    *,
    runtime: _ResolverRuntime,
    current_resolver: Any,
    target_scope: ScopePlan,
    context: Mapping[Any, Any] | None,
) -> Any:
    if (
        runtime.uses_stateless_scope_reuse
        and context is None
        and current_resolver._context is None
        and current_resolver._parent_context_resolver is None
    ):
        return getattr(
            current_resolver._root_resolver,
            f"_scope_resolver_{target_scope.scope_level}",
        )

    target_class = runtime.class_by_level[target_scope.scope_level]
    current_scope_plan = type(current_resolver)._class_plan
    root_resolver = (
        current_resolver if current_scope_plan.is_root else current_resolver._root_resolver
    )
    if runtime.has_cleanup:
        return target_class(
            root_resolver,
            current_resolver._cleanup_enabled,
            context,
            current_resolver,
        )
    return target_class(
        root_resolver,
        context,
        current_resolver,
    )


def _next_scope_options(
    *,
    runtime: _ResolverRuntime,
    class_scope_level: int,
) -> tuple[ScopePlan | None, ScopePlan | None, tuple[ScopePlan, ...]]:
    return runtime.next_scope_options_by_level.get(class_scope_level, (None, None, ()))


def _build_transition_plan_to_target(
    *,
    runtime: _ResolverRuntime,
    class_scope_level: int,
    target_scope_level: int,
) -> tuple[ScopePlan, ...]:
    if target_scope_level <= class_scope_level:
        msg = "Transition target scope level must be deeper than current scope level."
        raise ValueError(msg)

    transition_plan: list[ScopePlan] = []
    current_scope_level = class_scope_level

    while current_scope_level < target_scope_level:
        immediate_next, default_next, _ = _next_scope_options(
            runtime=runtime,
            class_scope_level=current_scope_level,
        )
        if immediate_next is None or default_next is None:
            msg = f"Cannot build transition plan from scope level {class_scope_level}."
            raise ValueError(msg)

        if immediate_next.scope_level == target_scope_level:
            next_scope = immediate_next
        elif default_next.scope_level <= target_scope_level:
            next_scope = default_next
        else:
            next_scope = immediate_next

        transition_plan.append(next_scope)
        current_scope_level = next_scope.scope_level

    return tuple(transition_plan)


def _resolver_resolve_from_context(self: Any, key: Any) -> Any:
    context = self._context
    if context is not None and key in context:
        return context[key]

    parent_context_resolver = self._parent_context_resolver
    while parent_context_resolver is not None:
        parent_context = parent_context_resolver._context
        if parent_context is not None and key in parent_context:
            return parent_context[key]
        parent_context_resolver = parent_context_resolver._parent_context_resolver

    msg = (
        f"Context value for {key!r} is not provided. Pass it via "
        "`enter_scope(..., context={...})` (or "
        f"`{INJECT_CONTEXT_KWARG}` for injected callables)."
    )
    raise DIWireDependencyNotRegisteredError(msg)


def _resolver_is_registered_dependency(self: Any, dependency: Any) -> bool:
    runtime = type(self)._runtime
    return dependency in runtime.dep_registered_keys


def _resolver_exit(
    self: Any,
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: TracebackType | None,
) -> None:
    cleanup_error: BaseException | None = None

    while self._cleanup_callbacks:
        cleanup_kind, cleanup = self._cleanup_callbacks.pop()
        try:
            if cleanup_kind == 0:
                cleanup(exc_type, exc_value, traceback)
            else:
                msg = "Cannot execute async cleanup in sync context. Use 'async with'."
                raise DIWireAsyncDependencyInSyncContextError(msg)
        except BaseException as error:  # noqa: BLE001
            if exc_type is None and cleanup_error is None:
                cleanup_error = error

    if self._owned_scope_resolvers:
        for owned_scope_resolver in reversed(self._owned_scope_resolvers):
            try:
                owned_scope_resolver.__exit__(exc_type, exc_value, traceback)
            except BaseException as error:  # noqa: BLE001
                if exc_type is None and cleanup_error is None:
                    cleanup_error = error

    self._active = False
    if exc_type is None and cleanup_error is not None:
        raise cleanup_error


def _resolver_aexit(
    self: Any,
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: TracebackType | None,
) -> Awaitable[None]:
    async def _run() -> None:
        cleanup_error: BaseException | None = None

        while self._cleanup_callbacks:
            cleanup_kind, cleanup = self._cleanup_callbacks.pop()
            try:
                if cleanup_kind == 0:
                    cleanup(exc_type, exc_value, traceback)
                else:
                    await cleanup(exc_type, exc_value, traceback)
            except BaseException as error:  # noqa: BLE001
                if exc_type is None and cleanup_error is None:
                    cleanup_error = error

        if self._owned_scope_resolvers:
            for owned_scope_resolver in reversed(self._owned_scope_resolvers):
                try:
                    await owned_scope_resolver.__aexit__(exc_type, exc_value, traceback)
                except BaseException as error:  # noqa: BLE001
                    if exc_type is None and cleanup_error is None:
                        cleanup_error = error

        self._active = False
        if exc_type is None and cleanup_error is not None:
            raise cleanup_error

    return _run()


def _resolve_dispatch_fallback_sync(self: Any, dependency: Any) -> Any:
    if is_maybe_annotation(dependency):
        inner = strip_maybe_annotation(dependency)
        if is_provider_annotation(inner):
            provider_inner = strip_provider_annotation(inner)
            if is_async_provider_annotation(inner):
                return lambda: self.aresolve(provider_inner)
            return lambda: self.resolve(provider_inner)

        if is_from_context_annotation(inner):
            key = strip_from_context_annotation(inner)
            try:
                return self._resolve_from_context(key)
            except DIWireDependencyNotRegisteredError:
                return None

        if not self._is_registered_dependency(inner):
            return None
        return self.resolve(inner)

    if is_provider_annotation(dependency):
        inner = strip_provider_annotation(dependency)
        if is_async_provider_annotation(dependency):
            return lambda: self.aresolve(inner)
        return lambda: self.resolve(inner)

    if is_from_context_annotation(dependency):
        key = strip_from_context_annotation(dependency)
        return self._resolve_from_context(key)

    if is_all_annotation(dependency):
        runtime = type(self)._runtime
        inner = strip_all_annotation(dependency)
        slots = runtime.all_slots_by_key.get(inner, ())
        if not slots:
            return ()

        results: list[Any] = []
        for slot in slots:
            results.append(getattr(self, f"resolve_{slot}")())
        return tuple(results)

    msg = f"Dependency {dependency!r} is not registered."
    raise DIWireDependencyNotRegisteredError(msg)


def _resolve_dispatch_fallback_async(self: Any, dependency: Any) -> Awaitable[Any]:
    async def _run() -> Any:
        if is_maybe_annotation(dependency):
            inner = strip_maybe_annotation(dependency)
            if is_provider_annotation(inner):
                provider_inner = strip_provider_annotation(inner)
                if is_async_provider_annotation(inner):
                    return lambda: self.aresolve(provider_inner)
                return lambda: self.resolve(provider_inner)

            if is_from_context_annotation(inner):
                key = strip_from_context_annotation(inner)
                try:
                    return self._resolve_from_context(key)
                except DIWireDependencyNotRegisteredError:
                    return None

            if not self._is_registered_dependency(inner):
                return None
            return await self.aresolve(inner)

        if is_provider_annotation(dependency):
            inner = strip_provider_annotation(dependency)
            if is_async_provider_annotation(dependency):
                return lambda: self.aresolve(inner)
            return lambda: self.resolve(inner)

        if is_from_context_annotation(dependency):
            key = strip_from_context_annotation(dependency)
            return self._resolve_from_context(key)

        if is_all_annotation(dependency):
            runtime = type(self)._runtime
            inner = strip_all_annotation(dependency)
            slots = runtime.all_slots_by_key.get(inner, ())
            if not slots:
                return ()

            results: list[Any] = []
            for slot in slots:
                results.append(await getattr(self, f"aresolve_{slot}")())
            return tuple(results)

        msg = f"Dependency {dependency!r} is not registered."
        raise DIWireDependencyNotRegisteredError(msg)

    return _run()


def _build_sync_slot_impl(*, workflow: ProviderWorkflowPlan) -> Callable[[Any], Any]:
    def _impl(self: Any) -> Any:
        runtime = type(self)._runtime
        class_scope_level = type(self)._class_plan.scope_level

        owner_scope_level = workflow.cache_owner_scope_level
        if (
            workflow.is_cached
            and owner_scope_level is not None
            and owner_scope_level != class_scope_level
        ):
            if owner_scope_level > class_scope_level:
                _raise_scope_mismatch(workflow=workflow)
            owner_resolver = _owner_resolver_for_scope(
                runtime=runtime,
                resolver=self,
                scope_level=owner_scope_level,
                workflow=workflow,
            )
            return getattr(owner_resolver, f"resolve_{workflow.slot}")()

        provider_scope_resolver = _provider_scope_resolver_for_workflow(
            runtime=runtime,
            resolver=self,
            class_scope_level=class_scope_level,
            workflow=workflow,
        )

        if (
            workflow.scope_level < class_scope_level
            and workflow.max_required_scope_level <= workflow.scope_level
        ):
            owner_resolver = _owner_resolver_for_scope(
                runtime=runtime,
                resolver=self,
                scope_level=workflow.scope_level,
                workflow=workflow,
            )
            return getattr(owner_resolver, f"resolve_{workflow.slot}")()

        if workflow.requires_async:
            msg = f"Provider slot {workflow.slot} requires asynchronous resolution."
            raise DIWireAsyncDependencyInSyncContextError(msg)

        if workflow.uses_thread_lock:
            cache_attr = f"_cache_{workflow.slot}"
            cached_value = getattr(self, cache_attr)
            if cached_value is not _MISSING_CACHE:
                return cached_value

            lock = runtime.thread_lock_by_slot[workflow.slot]
            with lock:
                cached_value = getattr(self, cache_attr)
                if cached_value is not _MISSING_CACHE:
                    return cached_value

                value = _build_local_value_sync(
                    runtime=runtime,
                    resolver=self,
                    workflow=workflow,
                    provider_scope_resolver=provider_scope_resolver,
                )
                _replace_sync_cache(
                    runtime=runtime,
                    resolver=self,
                    workflow=workflow,
                    value=value,
                )
                return value

        if workflow.is_cached:
            cache_attr = f"_cache_{workflow.slot}"
            cached_value = getattr(self, cache_attr)
            if cached_value is _MISSING_CACHE:
                value = _build_local_value_sync(
                    runtime=runtime,
                    resolver=self,
                    workflow=workflow,
                    provider_scope_resolver=provider_scope_resolver,
                )
                _replace_sync_cache(
                    runtime=runtime,
                    resolver=self,
                    workflow=workflow,
                    value=value,
                )
                return value
            return cached_value

        value = _build_local_value_sync(
            runtime=runtime,
            resolver=self,
            workflow=workflow,
            provider_scope_resolver=provider_scope_resolver,
        )
        _replace_sync_cache(
            runtime=runtime,
            resolver=self,
            workflow=workflow,
            value=value,
        )
        return value

    return _impl


def _build_async_slot_impl(*, workflow: ProviderWorkflowPlan) -> Callable[[Any], Awaitable[Any]]:
    async def _impl(self: Any) -> Any:
        runtime = type(self)._runtime
        class_scope_level = type(self)._class_plan.scope_level

        if not workflow.requires_async:
            return getattr(self, f"resolve_{workflow.slot}")()

        owner_scope_level = workflow.cache_owner_scope_level
        if (
            workflow.is_cached
            and owner_scope_level is not None
            and owner_scope_level != class_scope_level
        ):
            if owner_scope_level > class_scope_level:
                _raise_scope_mismatch(workflow=workflow)
            owner_resolver = _owner_resolver_for_scope(
                runtime=runtime,
                resolver=self,
                scope_level=owner_scope_level,
                workflow=workflow,
            )
            return await getattr(owner_resolver, f"aresolve_{workflow.slot}")()

        provider_scope_resolver = _provider_scope_resolver_for_workflow(
            runtime=runtime,
            resolver=self,
            class_scope_level=class_scope_level,
            workflow=workflow,
        )

        if (
            workflow.scope_level < class_scope_level
            and workflow.max_required_scope_level <= workflow.scope_level
        ):
            owner_resolver = _owner_resolver_for_scope(
                runtime=runtime,
                resolver=self,
                scope_level=workflow.scope_level,
                workflow=workflow,
            )
            return await getattr(owner_resolver, f"aresolve_{workflow.slot}")()

        if workflow.uses_async_lock:
            cache_attr = f"_cache_{workflow.slot}"
            cached_value = getattr(self, cache_attr)
            if cached_value is not _MISSING_CACHE:
                return cached_value

            lock = runtime.async_lock_by_slot[workflow.slot]
            async with lock:
                cached_value = getattr(self, cache_attr)
                if cached_value is not _MISSING_CACHE:
                    return cached_value

                value = await _build_local_value_async(
                    runtime=runtime,
                    resolver=self,
                    workflow=workflow,
                    provider_scope_resolver=provider_scope_resolver,
                )
                _replace_async_cache(
                    runtime=runtime,
                    resolver=self,
                    workflow=workflow,
                    value=value,
                )
                return value

        if workflow.is_cached:
            cache_attr = f"_cache_{workflow.slot}"
            cached_value = getattr(self, cache_attr)
            if cached_value is _MISSING_CACHE:
                value = await _build_local_value_async(
                    runtime=runtime,
                    resolver=self,
                    workflow=workflow,
                    provider_scope_resolver=provider_scope_resolver,
                )
                _replace_async_cache(
                    runtime=runtime,
                    resolver=self,
                    workflow=workflow,
                    value=value,
                )
                return value
            return cached_value

        value = await _build_local_value_async(
            runtime=runtime,
            resolver=self,
            workflow=workflow,
            provider_scope_resolver=provider_scope_resolver,
        )
        _replace_async_cache(
            runtime=runtime,
            resolver=self,
            workflow=workflow,
            value=value,
        )
        return value

    return _impl


def _build_local_value_sync(
    *,
    runtime: _ResolverRuntime,
    resolver: Any,
    workflow: ProviderWorkflowPlan,
    provider_scope_resolver: Any,
) -> Any:
    provider = runtime.provider_by_slot[workflow.slot]

    if workflow.provider_attribute == "instance":
        return provider

    if (
        not workflow.dependency_plans
        and not workflow.dependencies
        and not workflow.provider_is_inject_wrapper
    ):
        return _build_local_value_sync_no_arguments(
            resolver=resolver,
            workflow=workflow,
            provider_scope_resolver=provider_scope_resolver,
            provider=provider,
        )

    argument_parts = _build_argument_parts_sync(
        runtime=runtime,
        resolver=resolver,
        workflow=workflow,
    )

    if workflow.provider_attribute in {"concrete_type", "factory"}:
        value = _call_provider(callable_obj=provider, argument_parts=argument_parts)
        if workflow.is_provider_async:
            value = _awaitable_in_sync(value=value, slot=workflow.slot)
        return value

    if workflow.provider_attribute == "generator":
        if workflow.is_provider_async:
            msg = f"Async generator provider slot {workflow.slot} cannot be resolved synchronously."
            raise DIWireAsyncDependencyInSyncContextError(msg)
        if provider_scope_resolver is _MISSING_RESOLVER:
            _raise_scope_mismatch(workflow=workflow)

        if resolver._cleanup_enabled:
            provider_cm = _call_provider(
                callable_obj=contextmanager(provider),
                argument_parts=argument_parts,
            )
            value = provider_cm.__enter__()
            provider_scope_resolver._cleanup_callbacks.append((0, provider_cm.__exit__))
            return value

        provider_gen = _call_provider(callable_obj=provider, argument_parts=argument_parts)
        return next(provider_gen)

    if workflow.provider_attribute == "context_manager":
        if provider_scope_resolver is _MISSING_RESOLVER:
            _raise_scope_mismatch(workflow=workflow)

        provider_cm = _call_provider(callable_obj=provider, argument_parts=argument_parts)
        if workflow.is_provider_async:
            msg = (
                f"Async context-manager provider slot {workflow.slot} cannot be resolved "
                "synchronously."
            )
            raise DIWireAsyncDependencyInSyncContextError(msg)

        value = provider_cm.__enter__()
        if resolver._cleanup_enabled:
            provider_scope_resolver._cleanup_callbacks.append((0, provider_cm.__exit__))
        return value

    msg = f"Unsupported provider attribute {workflow.provider_attribute!r}."
    raise ValueError(msg)


def _build_local_value_async(
    *,
    runtime: _ResolverRuntime,
    resolver: Any,
    workflow: ProviderWorkflowPlan,
    provider_scope_resolver: Any,
) -> Awaitable[Any]:
    async def _run() -> Any:
        provider = runtime.provider_by_slot[workflow.slot]

        if workflow.provider_attribute == "instance":
            return provider

        if (
            not workflow.dependency_plans
            and not workflow.dependencies
            and not workflow.provider_is_inject_wrapper
        ):
            return await _build_local_value_async_no_arguments(
                resolver=resolver,
                workflow=workflow,
                provider_scope_resolver=provider_scope_resolver,
                provider=provider,
            )

        argument_parts = await _build_argument_parts_async(
            runtime=runtime,
            resolver=resolver,
            workflow=workflow,
        )

        if workflow.provider_attribute in {"concrete_type", "factory"}:
            value = _call_provider(callable_obj=provider, argument_parts=argument_parts)
            if workflow.is_provider_async:
                return await cast("Awaitable[Any]", value)
            return value

        if workflow.provider_attribute == "generator":
            if provider_scope_resolver is _MISSING_RESOLVER:
                _raise_scope_mismatch(workflow=workflow)

            if workflow.is_provider_async:
                if resolver._cleanup_enabled:
                    provider_cm = _call_provider(
                        callable_obj=asynccontextmanager(provider),
                        argument_parts=argument_parts,
                    )
                    value = await provider_cm.__aenter__()
                    provider_scope_resolver._cleanup_callbacks.append((1, provider_cm.__aexit__))
                    return value

                provider_gen = _call_provider(callable_obj=provider, argument_parts=argument_parts)
                return await anext(provider_gen)

            if resolver._cleanup_enabled:
                provider_cm = _call_provider(
                    callable_obj=contextmanager(provider),
                    argument_parts=argument_parts,
                )
                value = provider_cm.__enter__()
                provider_scope_resolver._cleanup_callbacks.append((0, provider_cm.__exit__))
                return value

            provider_gen = _call_provider(callable_obj=provider, argument_parts=argument_parts)
            return next(provider_gen)

        if workflow.provider_attribute == "context_manager":
            if provider_scope_resolver is _MISSING_RESOLVER:
                _raise_scope_mismatch(workflow=workflow)

            provider_cm = _call_provider(callable_obj=provider, argument_parts=argument_parts)
            if workflow.is_provider_async:
                value = await provider_cm.__aenter__()
                if resolver._cleanup_enabled:
                    provider_scope_resolver._cleanup_callbacks.append((1, provider_cm.__aexit__))
                return value

            value = provider_cm.__enter__()
            if resolver._cleanup_enabled:
                provider_scope_resolver._cleanup_callbacks.append((0, provider_cm.__exit__))
            return value

        msg = f"Unsupported provider attribute {workflow.provider_attribute!r}."
        raise ValueError(msg)

    return _run()


def _awaitable_in_sync(*, value: Any, slot: int) -> Any:
    if inspect.isawaitable(value):
        msg = f"Provider slot {slot} requires asynchronous resolution."
        raise DIWireAsyncDependencyInSyncContextError(msg)
    return value


def _build_local_value_sync_no_arguments(
    *,
    resolver: Any,
    workflow: ProviderWorkflowPlan,
    provider_scope_resolver: Any,
    provider: Any,
) -> Any:
    if workflow.provider_attribute in {"concrete_type", "factory"}:
        value = provider()
        if workflow.is_provider_async:
            value = _awaitable_in_sync(value=value, slot=workflow.slot)
        return value

    if workflow.provider_attribute == "generator":
        if workflow.is_provider_async:
            msg = f"Async generator provider slot {workflow.slot} cannot be resolved synchronously."
            raise DIWireAsyncDependencyInSyncContextError(msg)
        if provider_scope_resolver is _MISSING_RESOLVER:
            _raise_scope_mismatch(workflow=workflow)

        if resolver._cleanup_enabled:
            provider_cm = contextmanager(provider)()
            value = provider_cm.__enter__()
            provider_scope_resolver._cleanup_callbacks.append((0, provider_cm.__exit__))
            return value

        provider_gen = provider()
        return next(provider_gen)

    if workflow.provider_attribute == "context_manager":
        if provider_scope_resolver is _MISSING_RESOLVER:
            _raise_scope_mismatch(workflow=workflow)
        provider_cm = provider()
        if workflow.is_provider_async:
            msg = (
                f"Async context-manager provider slot {workflow.slot} cannot be resolved "
                "synchronously."
            )
            raise DIWireAsyncDependencyInSyncContextError(msg)
        value = provider_cm.__enter__()
        if resolver._cleanup_enabled:
            provider_scope_resolver._cleanup_callbacks.append((0, provider_cm.__exit__))
        return value

    msg = f"Unsupported provider attribute {workflow.provider_attribute!r}."
    raise ValueError(msg)


def _build_local_value_async_no_arguments(
    *,
    resolver: Any,
    workflow: ProviderWorkflowPlan,
    provider_scope_resolver: Any,
    provider: Any,
) -> Awaitable[Any]:
    async def _run() -> Any:
        if workflow.provider_attribute in {"concrete_type", "factory"}:
            value = provider()
            if workflow.is_provider_async:
                return await cast("Awaitable[Any]", value)
            return value

        if workflow.provider_attribute == "generator":
            if provider_scope_resolver is _MISSING_RESOLVER:
                _raise_scope_mismatch(workflow=workflow)

            if workflow.is_provider_async:
                if resolver._cleanup_enabled:
                    provider_async_cm = asynccontextmanager(provider)()
                    value = await provider_async_cm.__aenter__()
                    provider_scope_resolver._cleanup_callbacks.append(
                        (1, provider_async_cm.__aexit__)
                    )
                    return value
                provider_async_gen = provider()
                return await anext(provider_async_gen)

            if resolver._cleanup_enabled:
                provider_sync_cm = contextmanager(provider)()
                value = provider_sync_cm.__enter__()
                provider_scope_resolver._cleanup_callbacks.append((0, provider_sync_cm.__exit__))
                return value

            provider_sync_gen = provider()
            return next(provider_sync_gen)

        if workflow.provider_attribute == "context_manager":
            if provider_scope_resolver is _MISSING_RESOLVER:
                _raise_scope_mismatch(workflow=workflow)

            provider_cm = provider()
            if workflow.is_provider_async:
                value = await provider_cm.__aenter__()
                if resolver._cleanup_enabled:
                    provider_scope_resolver._cleanup_callbacks.append((1, provider_cm.__aexit__))
                return value

            value = provider_cm.__enter__()
            if resolver._cleanup_enabled:
                provider_scope_resolver._cleanup_callbacks.append((0, provider_cm.__exit__))
            return value

        msg = f"Unsupported provider attribute {workflow.provider_attribute!r}."
        raise ValueError(msg)

    return _run()


def _build_argument_parts_sync(
    *,
    runtime: _ResolverRuntime,
    resolver: Any,
    workflow: ProviderWorkflowPlan,
) -> list[_ArgumentPart]:
    dependency_plans = workflow.dependency_plans
    if not dependency_plans and workflow.dependencies:
        dependency_plans = _dependency_plans_for_workflow(workflow=workflow)
    if not dependency_plans and not workflow.provider_is_inject_wrapper:
        return []

    argument_parts: list[_ArgumentPart] = []
    prefer_positional = workflow.dependency_order_is_signature_order
    skip_positional_only = False

    for dependency_plan in dependency_plans:
        dependency = dependency_plan.dependency
        parameter_kind = dependency.parameter.kind

        if skip_positional_only and parameter_kind is inspect.Parameter.POSITIONAL_ONLY:
            continue

        value = _resolve_dependency_value_sync(
            runtime=runtime,
            resolver=resolver,
            dependency_plan=dependency_plan,
        )

        if value is _OMIT_ARGUMENT:
            if parameter_kind in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }:
                prefer_positional = False
            if parameter_kind is inspect.Parameter.POSITIONAL_ONLY:
                skip_positional_only = True
            continue

        argument_part = _argument_part_for_dependency(
            dependency=dependency,
            value=value,
            prefer_positional=prefer_positional,
        )
        argument_parts.append(argument_part)

    if workflow.provider_is_inject_wrapper:
        _insert_internal_resolver_argument(
            argument_parts=argument_parts,
            resolver=resolver,
        )

    return argument_parts


def _build_argument_parts_async(
    *,
    runtime: _ResolverRuntime,
    resolver: Any,
    workflow: ProviderWorkflowPlan,
) -> Awaitable[list[_ArgumentPart]]:
    dependency_plans = workflow.dependency_plans
    if not dependency_plans and workflow.dependencies:
        dependency_plans = _dependency_plans_for_workflow(workflow=workflow)
    if not dependency_plans and not workflow.provider_is_inject_wrapper:

        async def _empty() -> list[_ArgumentPart]:
            return []

        return _empty()

    async def _run() -> list[_ArgumentPart]:
        argument_parts: list[_ArgumentPart] = []
        prefer_positional = workflow.dependency_order_is_signature_order
        skip_positional_only = False

        for dependency_plan in dependency_plans:
            dependency = dependency_plan.dependency
            parameter_kind = dependency.parameter.kind

            if skip_positional_only and parameter_kind is inspect.Parameter.POSITIONAL_ONLY:
                continue

            value = await _resolve_dependency_value_async(
                runtime=runtime,
                resolver=resolver,
                dependency_plan=dependency_plan,
            )

            if value is _OMIT_ARGUMENT:
                if parameter_kind in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                }:
                    prefer_positional = False
                if parameter_kind is inspect.Parameter.POSITIONAL_ONLY:
                    skip_positional_only = True
                continue

            argument_part = _argument_part_for_dependency(
                dependency=dependency,
                value=value,
                prefer_positional=prefer_positional,
            )
            argument_parts.append(argument_part)

        if workflow.provider_is_inject_wrapper:
            _insert_internal_resolver_argument(
                argument_parts=argument_parts,
                resolver=resolver,
            )

        return argument_parts

    return _run()


def _resolve_dependency_value_sync(
    *,
    runtime: _ResolverRuntime,
    resolver: Any,
    dependency_plan: ProviderDependencyPlan,
) -> Any:
    if dependency_plan.kind == "omit":
        return _OMIT_ARGUMENT

    if dependency_plan.kind == "literal":
        return _literal_value_for_plan(dependency_plan=dependency_plan)

    if dependency_plan.kind == "provider_handle":
        provider_inner_slot = dependency_plan.provider_inner_slot
        if provider_inner_slot is None:
            msg = "Missing provider inner slot for provider-handle dependency plan."
            raise ValueError(msg)

        if dependency_plan.provider_is_async:
            return lambda: getattr(resolver, f"aresolve_{provider_inner_slot}")()
        return lambda: getattr(resolver, f"resolve_{provider_inner_slot}")()

    if dependency_plan.kind == "context":
        context_key_name = dependency_plan.ctx_key_global_name
        if context_key_name is None:
            msg = "Missing context key global name for context dependency plan."
            raise ValueError(msg)
        context_key = runtime.context_key_by_name[context_key_name]
        return resolver._resolve_from_context(context_key)

    if dependency_plan.kind == "all":
        if not dependency_plan.all_slots:
            return ()

        values: list[Any] = []
        for slot in dependency_plan.all_slots:
            dependency_workflow = runtime.workflows_by_slot[slot]
            value = _dependency_value_for_slot_sync(
                runtime=runtime,
                resolver=resolver,
                dependency_workflow=dependency_workflow,
            )
            values.append(value)
        return tuple(values)

    dependency_slot = dependency_plan.dependency_slot
    if dependency_slot is None:
        msg = "Provider dependency plan is missing dependency slot."
        raise ValueError(msg)

    dependency_workflow = runtime.workflows_by_slot[dependency_slot]
    return _dependency_value_for_slot_sync(
        runtime=runtime,
        resolver=resolver,
        dependency_workflow=dependency_workflow,
    )


def _resolve_dependency_value_async(
    *,
    runtime: _ResolverRuntime,
    resolver: Any,
    dependency_plan: ProviderDependencyPlan,
) -> Awaitable[Any]:
    async def _run() -> Any:
        if dependency_plan.kind == "omit":
            return _OMIT_ARGUMENT

        if dependency_plan.kind == "literal":
            return _literal_value_for_plan(dependency_plan=dependency_plan)

        if dependency_plan.kind == "provider_handle":
            provider_inner_slot = dependency_plan.provider_inner_slot
            if provider_inner_slot is None:
                msg = "Missing provider inner slot for provider-handle dependency plan."
                raise ValueError(msg)

            if dependency_plan.provider_is_async:
                return lambda: getattr(resolver, f"aresolve_{provider_inner_slot}")()
            return lambda: getattr(resolver, f"resolve_{provider_inner_slot}")()

        if dependency_plan.kind == "context":
            context_key_name = dependency_plan.ctx_key_global_name
            if context_key_name is None:
                msg = "Missing context key global name for context dependency plan."
                raise ValueError(msg)
            context_key = runtime.context_key_by_name[context_key_name]
            return resolver._resolve_from_context(context_key)

        if dependency_plan.kind == "all":
            if not dependency_plan.all_slots:
                return ()

            values: list[Any] = []
            for slot in dependency_plan.all_slots:
                dependency_workflow = runtime.workflows_by_slot[slot]
                value = await _dependency_value_for_slot_async(
                    resolver=resolver,
                    dependency_workflow=dependency_workflow,
                    dependency_requires_async=dependency_workflow.requires_async,
                )
                values.append(value)
            return tuple(values)

        dependency_slot = dependency_plan.dependency_slot
        if dependency_slot is None:
            msg = "Provider dependency plan is missing dependency slot."
            raise ValueError(msg)

        dependency_workflow = runtime.workflows_by_slot[dependency_slot]
        return await _dependency_value_for_slot_async(
            resolver=resolver,
            dependency_workflow=dependency_workflow,
            dependency_requires_async=dependency_plan.dependency_requires_async,
        )

    return _run()


def _dependency_value_for_slot_sync(
    *,
    runtime: _ResolverRuntime,
    resolver: Any,
    dependency_workflow: ProviderWorkflowPlan,
) -> Any:
    class_scope_level = type(resolver)._class_plan.scope_level
    dependency_slot = dependency_workflow.slot

    if (
        dependency_workflow.is_cached
        and dependency_workflow.cache_owner_scope_level == class_scope_level
    ):
        cache_attr = f"_cache_{dependency_slot}"
        cached_value = getattr(resolver, cache_attr)
        if cached_value is not _MISSING_CACHE:
            return cached_value
        return getattr(resolver, f"resolve_{dependency_slot}")()

    if (
        dependency_workflow.scope_level < class_scope_level
        and dependency_workflow.max_required_scope_level <= dependency_workflow.scope_level
        and dependency_workflow.scope_level == runtime.root_scope_level
    ):
        root_resolver = (
            resolver if class_scope_level == runtime.root_scope_level else resolver._root_resolver
        )
        return getattr(root_resolver, f"resolve_{dependency_slot}")()

    return getattr(resolver, f"resolve_{dependency_slot}")()


def _dependency_value_for_slot_async(
    *,
    resolver: Any,
    dependency_workflow: ProviderWorkflowPlan,
    dependency_requires_async: bool,
) -> Awaitable[Any]:
    async def _run() -> Any:
        dependency_slot = dependency_workflow.slot
        if dependency_requires_async:
            return await getattr(resolver, f"aresolve_{dependency_slot}")()
        return getattr(resolver, f"resolve_{dependency_slot}")()

    return _run()


def _argument_part_for_dependency(
    *,
    dependency: ProviderDependency,
    value: Any,
    prefer_positional: bool,
) -> _ArgumentPart:
    kind = dependency.parameter.kind

    if kind is inspect.Parameter.POSITIONAL_ONLY:
        return _ArgumentPart(kind="arg", value=value)
    if kind is inspect.Parameter.POSITIONAL_OR_KEYWORD and prefer_positional:
        return _ArgumentPart(kind="arg", value=value)
    if kind is inspect.Parameter.VAR_POSITIONAL:
        return _ArgumentPart(kind="star", value=value)
    if kind is inspect.Parameter.VAR_KEYWORD:
        return _ArgumentPart(kind="starstar", value=value)

    parameter_name = dependency.parameter.name
    if not parameter_name.isidentifier() or keyword.iskeyword(parameter_name):
        msg = (
            f"Dependency parameter name {parameter_name!r} is not a valid identifier "
            "for generated keyword-argument wiring."
        )
        raise ValueError(msg)
    return _ArgumentPart(kind="kw", name=parameter_name, value=value)


def _insert_internal_resolver_argument(
    *, argument_parts: list[_ArgumentPart], resolver: Any
) -> None:
    resolver_part = _ArgumentPart(
        kind="kw",
        name=INJECT_RESOLVER_KWARG,
        value=resolver,
    )
    var_keyword_index = next(
        (
            index
            for index, argument_part in enumerate(argument_parts)
            if argument_part.kind == "starstar"
        ),
        None,
    )
    if var_keyword_index is None:
        argument_parts.append(resolver_part)
        return
    argument_parts.insert(var_keyword_index, resolver_part)


def _call_provider(*, callable_obj: Any, argument_parts: list[_ArgumentPart]) -> Any:
    if not argument_parts:
        return callable_obj()

    positional_arguments: list[Any] = []
    keyword_arguments: dict[str, Any] = {}
    seen_keyword_names: set[str] = set()

    for argument_part in argument_parts:
        if argument_part.kind == "arg":
            positional_arguments.append(argument_part.value)
            continue

        if argument_part.kind == "star":
            positional_arguments.extend(tuple(argument_part.value))
            continue

        if argument_part.kind == "kw":
            key = cast("str", argument_part.name)
            if key in seen_keyword_names:
                msg = f"Provider call received duplicate keyword argument {key!r}."
                raise TypeError(msg)
            seen_keyword_names.add(key)
            keyword_arguments[key] = argument_part.value
            continue

        mapping = dict(argument_part.value)
        for key, value in mapping.items():
            if key in seen_keyword_names:
                msg = f"Provider call received duplicate keyword argument {key!r}."
                raise TypeError(msg)
            seen_keyword_names.add(key)
            keyword_arguments[key] = value

    return callable_obj(*positional_arguments, **keyword_arguments)


def _literal_value_for_plan(*, dependency_plan: ProviderDependencyPlan) -> Any:
    literal_expression = dependency_plan.literal_expression
    if literal_expression == "None":
        return None
    if literal_expression == "()":
        return ()
    if literal_expression == "{}":
        return {}

    msg = f"Unsupported literal dependency expression {literal_expression!r}."
    raise ValueError(msg)


def _replace_sync_cache(
    *,
    runtime: _ResolverRuntime,
    resolver: Any,
    workflow: ProviderWorkflowPlan,
    value: Any,
) -> None:
    if not workflow.is_cached:
        return

    cache_attr = f"_cache_{workflow.slot}"
    setattr(resolver, cache_attr, value)

    if workflow.cache_owner_scope_level != runtime.root_scope_level:
        return

    setattr(resolver, f"resolve_{workflow.slot}", lambda: value)

    async def _cached() -> Any:
        return value

    setattr(resolver, f"aresolve_{workflow.slot}", _cached)


def _replace_async_cache(
    *,
    runtime: _ResolverRuntime,
    resolver: Any,
    workflow: ProviderWorkflowPlan,
    value: Any,
) -> None:
    if not workflow.is_cached:
        return

    cache_attr = f"_cache_{workflow.slot}"
    setattr(resolver, cache_attr, value)

    if workflow.cache_owner_scope_level != runtime.root_scope_level:
        return

    async def _cached() -> Any:
        return value

    setattr(resolver, f"aresolve_{workflow.slot}", _cached)


def _provider_scope_resolver_for_workflow(
    *,
    runtime: _ResolverRuntime,
    resolver: Any,
    class_scope_level: int,
    workflow: ProviderWorkflowPlan,
) -> Any:
    needs_scope_resolver = workflow.provider_attribute in {"generator", "context_manager"}

    if workflow.scope_level > class_scope_level:
        _raise_scope_mismatch(workflow=workflow)

    if workflow.scope_level == class_scope_level:
        if needs_scope_resolver:
            return resolver
        return _MISSING_RESOLVER

    scope = runtime.scopes_by_level[workflow.scope_level]
    scope_reference = getattr(resolver, scope.resolver_attr_name)
    if scope.is_root:
        if needs_scope_resolver:
            return scope_reference
        return _MISSING_RESOLVER

    if needs_scope_resolver:
        if scope_reference is _MISSING_RESOLVER:
            _raise_scope_mismatch(workflow=workflow)
        return scope_reference

    if scope_reference is _MISSING_RESOLVER:
        _raise_scope_mismatch(workflow=workflow)

    return _MISSING_RESOLVER


def _owner_resolver_for_scope(
    *,
    runtime: _ResolverRuntime,
    resolver: Any,
    scope_level: int,
    workflow: ProviderWorkflowPlan,
) -> Any:
    scope = runtime.scopes_by_level[scope_level]
    if scope.is_root:
        return resolver._root_resolver

    owner_resolver = getattr(resolver, scope.resolver_attr_name)
    if owner_resolver is _MISSING_RESOLVER:
        _raise_scope_mismatch(workflow=workflow)
    return owner_resolver


def _raise_scope_mismatch(*, workflow: ProviderWorkflowPlan) -> None:
    msg = f"Provider slot {workflow.slot} requires opened scope level {workflow.scope_level}."
    raise DIWireScopeMismatchError(msg)


def _resolver_scope_level(resolver: Any) -> int:
    return type(resolver)._class_plan.scope_level


def _dependency_plans_for_workflow(
    *,
    workflow: ProviderWorkflowPlan,
) -> tuple[ProviderDependencyPlan, ...]:
    if workflow.dependency_plans:
        return workflow.dependency_plans

    fallback_plans: list[ProviderDependencyPlan] = []
    for dependency_index, (dependency, slot, requires_async) in enumerate(
        zip(
            workflow.dependencies,
            workflow.dependency_slots,
            workflow.dependency_requires_async,
            strict=True,
        ),
    ):
        resolved_slot = slot if slot is not None and slot >= 0 else None
        fallback_plans.append(
            ProviderDependencyPlan(
                kind="provider" if resolved_slot is not None else "context",
                dependency=dependency,
                dependency_index=dependency_index,
                dependency_slot=resolved_slot,
                dependency_requires_async=requires_async,
            ),
        )
    return tuple(fallback_plans)


def _dispatch_workflows(
    *,
    plan: ResolverGenerationPlan,
    class_plan: ScopePlan,
) -> tuple[ProviderWorkflowPlan, ...]:
    return tuple(
        sorted(
            plan.workflows,
            key=lambda workflow: (
                workflow.scope_level != class_plan.scope_level,
                abs(workflow.scope_level - class_plan.scope_level),
                workflow.slot,
            ),
        ),
    )


def _dispatch_cache_enabled_for_class(
    *,
    plan: ResolverGenerationPlan,
    class_plan: ScopePlan,
) -> bool:
    return (
        len(_dispatch_workflows(plan=plan, class_plan=class_plan))
        >= _DISPATCH_CACHE_WORKFLOW_THRESHOLD
    )


def _unique_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values
