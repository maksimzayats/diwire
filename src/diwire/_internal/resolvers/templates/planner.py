from __future__ import annotations

import inspect
import keyword
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from diwire._internal.injection import INJECT_WRAPPER_MARKER
from diwire._internal.lock_mode import LockMode
from diwire._internal.markers import (
    component_base_key,
    is_all_annotation,
    is_async_provider_annotation,
    is_from_context_annotation,
    is_maybe_annotation,
    is_provider_annotation,
    strip_all_annotation,
    strip_maybe_annotation,
    strip_provider_annotation,
)
from diwire._internal.providers import (
    Lifetime,
    ProviderDependency,
    ProviderSpec,
    ProvidersRegistrations,
)
from diwire._internal.scope import BaseScope, BaseScopes
from diwire._internal.type_checks import is_runtime_class
from diwire.exceptions import DIWireDependencyNotRegisteredError, DIWireInvalidProviderSpecError

DispatchKind = Literal["identity", "equality_map"]
DependencyPlanKind = Literal["provider", "context", "provider_handle", "all", "literal", "omit"]


def validate_resolver_assembly_managed_scopes(*, root_scope: Any) -> tuple[BaseScope, ...]:
    """Validate scope metadata used by resolver code generation.

    Args:
        root_scope: Root scope candidate that owns managed resolver scopes.

    """
    if not isinstance(root_scope, BaseScope):
        msg = (
            "Invalid root scope for resolver code generation: expected BaseScope, "
            f"got {type(root_scope).__name__}."
        )
        raise DIWireInvalidProviderSpecError(msg)

    owner = getattr(root_scope, "owner", None)
    if owner is None:
        msg = (
            "Invalid root scope for resolver code generation: missing 'owner' attribute on "
            "root scope."
        )
        raise DIWireInvalidProviderSpecError(msg)
    if not isinstance(owner, type) or not issubclass(owner, BaseScopes):
        msg = (
            "Invalid root scope for resolver code generation: 'owner' must be a BaseScopes "
            f"subclass, got {type(owner).__name__}."
        )
        raise DIWireInvalidProviderSpecError(msg)

    try:
        managed_scope_owner = owner()
    except Exception as error:
        msg = (
            "Invalid root scope for resolver code generation: 'owner' must be callable and "
            "instantiable for scope iteration."
        )
        raise DIWireInvalidProviderSpecError(msg) from error

    root_scope_level = _validate_resolver_assembly_scope_level(scope=root_scope)
    managed_scopes: list[BaseScope] = []
    for scope in managed_scope_owner:
        _validate_resolver_assembly_scope(scope=scope)
        if scope.level >= root_scope_level:
            managed_scopes.append(scope)

    return tuple(managed_scopes)


def _validate_resolver_assembly_scope(scope: Any) -> None:
    if not isinstance(scope, BaseScope):
        msg = (
            "Invalid scope metadata for resolver code generation: expected BaseScope member, "
            f"got {type(scope).__name__}."
        )
        raise DIWireInvalidProviderSpecError(msg)

    scope_name = getattr(scope, "scope_name", None)
    if scope_name is None:
        msg = "Invalid scope metadata for resolver code generation: missing 'scope_name'."
        raise DIWireInvalidProviderSpecError(msg)
    if not isinstance(scope_name, str):
        msg = (
            "Invalid scope metadata for resolver code generation: 'scope_name' must be str, "
            f"got {type(scope_name).__name__}."
        )
        raise DIWireInvalidProviderSpecError(msg)
    if not scope_name.isidentifier():
        msg = (
            "Invalid scope metadata for resolver code generation: "
            f"scope_name '{scope_name}' is not a valid identifier."
        )
        raise DIWireInvalidProviderSpecError(msg)
    if keyword.iskeyword(scope_name):
        msg = (
            "Invalid scope metadata for resolver code generation: "
            f"scope_name '{scope_name}' is a Python keyword."
        )
        raise DIWireInvalidProviderSpecError(msg)

    _validate_resolver_assembly_scope_level(scope=scope)


def _validate_resolver_assembly_scope_level(*, scope: Any) -> int:
    scope_level = getattr(scope, "level", None)
    if scope_level is None:
        msg = "Invalid scope metadata for resolver code generation: missing 'level'."
        raise DIWireInvalidProviderSpecError(msg)
    if not isinstance(scope_level, int):
        msg = (
            "Invalid scope metadata for resolver code generation: 'level' must be int, "
            f"got {type(scope_level).__name__}."
        )
        raise DIWireInvalidProviderSpecError(msg)
    return scope_level


@dataclass(frozen=True, slots=True)
class ScopePlan:
    """Scope metadata used during class rendering."""

    scope_name: str
    scope_level: int
    class_name: str
    resolver_arg_name: str
    resolver_attr_name: str
    skippable: bool
    is_root: bool


@dataclass(frozen=True, slots=True)
class ProviderDependencyPlan:
    """Provider dependency plan item for generated wiring."""

    kind: DependencyPlanKind
    dependency: ProviderDependency
    dependency_index: int
    dependency_slot: int | None = None
    dependency_requires_async: bool = False
    ctx_key_global_name: str | None = None
    provider_inner_slot: int | None = None
    provider_is_async: bool = False
    all_slots: tuple[int, ...] = ()
    literal_expression: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderWorkflowPlan:
    """Provider metadata used during method rendering."""

    slot: int
    provides: Any
    provider_attribute: str
    provider_reference: Any
    lifetime: Lifetime | None
    scope_name: str
    scope_level: int
    scope_attr_name: str
    is_cached: bool
    is_transient: bool
    cache_owner_scope_level: int | None
    lock_mode: LockMode | Literal["auto"]
    effective_lock_mode: LockMode
    uses_thread_lock: bool
    uses_async_lock: bool
    is_provider_async: bool
    requires_async: bool
    needs_cleanup: bool
    dependencies: tuple[ProviderDependency, ...]
    dependency_slots: tuple[int | None, ...]
    dependency_requires_async: tuple[bool, ...]
    dependency_order_is_signature_order: bool
    max_required_scope_level: int
    dispatch_kind: DispatchKind
    sync_arguments: tuple[str, ...]
    async_arguments: tuple[str, ...]
    provider_is_inject_wrapper: bool = False
    dependency_plans: tuple[ProviderDependencyPlan, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolverGenerationPlan:
    """Deterministic plan consumed by the renderer."""

    root_scope_level: int
    has_async_specs: bool
    provider_count: int
    cached_provider_count: int
    thread_lock_count: int
    async_lock_count: int
    effective_mode_counts: tuple[tuple[LockMode, int], ...]
    has_cleanup: bool
    identity_dispatch_slots: tuple[int, ...]
    equality_dispatch_slots: tuple[int, ...]
    scopes: tuple[ScopePlan, ...]
    workflows: tuple[ProviderWorkflowPlan, ...]


class ResolverGenerationPlanner:
    """Builds deterministic metadata for resolver code generation."""

    def __init__(
        self,
        *,
        root_scope: BaseScope,
        registrations: ProvidersRegistrations,
    ) -> None:
        self._root_scope = root_scope
        self._registrations = registrations
        self._managed_scopes = validate_resolver_assembly_managed_scopes(root_scope=root_scope)
        self._work_specs = self._collect_specs()
        self._all_slots_by_key = self._build_all_slots_by_key()
        self._requires_async_by_slot = self._build_requires_async_by_slot()
        self._max_required_scope_level_by_slot = self._build_max_required_scope_level_by_slot()

    def build(self) -> ResolverGenerationPlan:
        """Build resolver generation metadata."""
        # Design contract:
        # - generated runtime stays class-first (RootResolver + scope resolver classes),
        # - cached providers use method replacement (lambda/async def),
        # - hot path avoids reflective dispatch or dynamic attribute lookup helpers.
        scopes = self._build_scope_plans()
        scope_by_level = {scope.scope_level: scope for scope in scopes}
        has_async_specs = any(spec.is_async for spec in self._work_specs)

        workflows = tuple(
            self._build_workflow_plan(
                spec=spec,
                scope_by_level=scope_by_level,
                has_async_specs=has_async_specs,
            )
            for spec in self._work_specs
        )

        has_cleanup = any(spec.needs_cleanup for spec in self._work_specs)
        provider_count = len(workflows)
        cached_provider_count = sum(1 for workflow in workflows if workflow.is_cached)
        thread_lock_count = sum(1 for workflow in workflows if workflow.uses_thread_lock)
        async_lock_count = sum(1 for workflow in workflows if workflow.uses_async_lock)
        effective_mode_counter = Counter(workflow.effective_lock_mode for workflow in workflows)
        effective_mode_counts = tuple(
            (mode, effective_mode_counter.get(mode, 0))
            for mode in (LockMode.THREAD, LockMode.ASYNC, LockMode.NONE)
        )
        identity_dispatch_slots = tuple(
            workflow.slot for workflow in workflows if workflow.dispatch_kind == "identity"
        )
        equality_dispatch_slots = tuple(
            workflow.slot for workflow in workflows if workflow.dispatch_kind == "equality_map"
        )

        return ResolverGenerationPlan(
            root_scope_level=self._root_scope.level,
            has_async_specs=has_async_specs,
            provider_count=provider_count,
            cached_provider_count=cached_provider_count,
            thread_lock_count=thread_lock_count,
            async_lock_count=async_lock_count,
            effective_mode_counts=effective_mode_counts,
            has_cleanup=has_cleanup,
            identity_dispatch_slots=identity_dispatch_slots,
            equality_dispatch_slots=equality_dispatch_slots,
            scopes=scopes,
            workflows=workflows,
        )

    def _collect_specs(self) -> tuple[ProviderSpec, ...]:
        specs = [
            spec
            for spec in self._registrations.values()
            if spec.scope.level >= self._root_scope.level
        ]
        return tuple(sorted(specs, key=lambda item: item.slot))

    def _build_scope_plans(self) -> tuple[ScopePlan, ...]:
        ordered_scopes = sorted(self._managed_scopes, key=lambda scope: scope.level)

        plans: list[ScopePlan] = []
        for scope in ordered_scopes:
            scope_name = scope.scope_name.lower()
            plans.append(
                ScopePlan(
                    scope_name=scope_name,
                    scope_level=scope.level,
                    class_name=(
                        "RootResolver"
                        if scope.level == self._root_scope.level
                        else f"_{scope.scope_name.capitalize()}Resolver"
                    ),
                    resolver_arg_name=(
                        "root_resolver"
                        if scope.level == self._root_scope.level
                        else f"{scope_name}_resolver"
                    ),
                    resolver_attr_name=(
                        "_root_resolver"
                        if scope.level == self._root_scope.level
                        else f"_{scope_name}_resolver"
                    ),
                    skippable=scope.skippable,
                    is_root=scope.level == self._root_scope.level,
                ),
            )
        return tuple(plans)

    def _build_workflow_plan(
        self,
        *,
        spec: ProviderSpec,
        scope_by_level: dict[int, ScopePlan],
        has_async_specs: bool,
    ) -> ProviderWorkflowPlan:
        provider_attribute = self._resolve_provider_attribute(spec=spec)
        provider_reference = getattr(spec, provider_attribute)
        is_cached = self._is_cached(spec=spec)
        cache_owner_scope_level = self._cache_owner_scope_level(spec=spec, is_cached=is_cached)

        dependency_plans: list[ProviderDependencyPlan] = []
        dependency_slots: list[int | None] = []
        dependency_requires_async: list[bool] = []
        sync_arguments: list[str] = []
        async_arguments: list[str] = []
        for dependency_index, dependency in enumerate(spec.dependencies):
            dependency_plan, slot, requires_async, sync_argument, async_argument = (
                self._plan_dependency(
                    spec=spec,
                    dependency_index=dependency_index,
                    dependency=dependency,
                )
            )
            dependency_plans.append(dependency_plan)
            dependency_slots.append(slot)
            dependency_requires_async.append(requires_async)
            sync_arguments.append(sync_argument)
            async_arguments.append(async_argument)

        scope_plan = scope_by_level[spec.scope.level]
        requires_async = self._requires_async_by_slot[spec.slot]
        effective_lock_mode = self._resolve_effective_lock_mode(
            lock_mode=spec.lock_mode,
            has_async_specs=has_async_specs,
        )
        uses_thread_lock = (
            is_cached and effective_lock_mode is LockMode.THREAD and not requires_async
        )
        uses_async_lock = is_cached and effective_lock_mode is LockMode.ASYNC and requires_async
        dispatch_kind = self._resolve_dispatch_kind(provides=spec.provides)

        return ProviderWorkflowPlan(
            slot=spec.slot,
            provides=spec.provides,
            provider_attribute=provider_attribute,
            provider_reference=provider_reference,
            lifetime=spec.lifetime,
            scope_name=scope_plan.scope_name,
            scope_level=scope_plan.scope_level,
            scope_attr_name=scope_plan.resolver_attr_name,
            is_cached=is_cached,
            is_transient=not is_cached,
            cache_owner_scope_level=cache_owner_scope_level,
            lock_mode=spec.lock_mode,
            effective_lock_mode=effective_lock_mode,
            uses_thread_lock=uses_thread_lock,
            uses_async_lock=uses_async_lock,
            is_provider_async=spec.is_async,
            requires_async=requires_async,
            needs_cleanup=spec.needs_cleanup,
            dependencies=tuple(spec.dependencies),
            dependency_slots=tuple(dependency_slots),
            dependency_requires_async=tuple(dependency_requires_async),
            dependency_order_is_signature_order=self._dependency_order_is_signature_order(
                spec=spec,
            ),
            max_required_scope_level=self._max_required_scope_level_by_slot[spec.slot],
            dispatch_kind=dispatch_kind,
            sync_arguments=tuple(sync_arguments),
            async_arguments=tuple(async_arguments),
            provider_is_inject_wrapper=bool(
                getattr(provider_reference, INJECT_WRAPPER_MARKER, False),
            ),
            dependency_plans=tuple(dependency_plans),
        )

    def _plan_dependency(
        self,
        *,
        spec: ProviderSpec,
        dependency_index: int,
        dependency: ProviderDependency,
    ) -> tuple[ProviderDependencyPlan, int | None, bool, str, str]:
        optional, dependency_key = self._split_maybe_dependency(dependency.provides)
        if is_from_context_annotation(dependency_key):
            return self._plan_context_dependency(
                provider_slot=spec.slot,
                dependency_index=dependency_index,
                dependency=dependency,
            )
        if is_provider_annotation(dependency_key):
            return self._plan_provider_handle_dependency(
                spec=spec,
                dependency_index=dependency_index,
                dependency=dependency,
                dependency_key=dependency_key,
            )
        if is_all_annotation(dependency_key):
            return self._plan_all_dependency(
                dependency_index=dependency_index,
                dependency=dependency,
                dependency_key=dependency_key,
            )
        return self._plan_provider_dependency(
            spec=spec,
            dependency_index=dependency_index,
            dependency=dependency,
            dependency_key=dependency_key,
            optional=optional,
        )

    def _plan_context_dependency(
        self,
        *,
        provider_slot: int,
        dependency_index: int,
        dependency: ProviderDependency,
    ) -> tuple[ProviderDependencyPlan, int | None, bool, str, str]:
        ctx_key_global_name = f"_ctx_{provider_slot}_{dependency_index}_key"
        plan = ProviderDependencyPlan(
            kind="context",
            dependency=dependency,
            dependency_index=dependency_index,
            dependency_slot=None,
            dependency_requires_async=False,
            ctx_key_global_name=ctx_key_global_name,
        )
        expression = f"self._resolve_from_context({ctx_key_global_name})"
        argument = self._format_dependency_argument_for_expression(
            dependency=dependency,
            expression=expression,
        )
        return plan, None, False, argument, argument

    def _plan_provider_handle_dependency(
        self,
        *,
        spec: ProviderSpec,
        dependency_index: int,
        dependency: ProviderDependency,
        dependency_key: Any,
    ) -> tuple[ProviderDependencyPlan, int | None, bool, str, str]:
        parameter_kind = dependency.parameter.kind
        if parameter_kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            msg = (
                "Provider and AsyncProvider dependencies are not supported for "
                f"star parameters (*args/**kwargs): {dependency.parameter.name!r}."
            )
            raise DIWireInvalidProviderSpecError(msg)
        provider_inner_key = strip_provider_annotation(dependency_key)
        provider_inner_spec = self._dependency_spec_or_error(
            dependency_provides=provider_inner_key,
            requiring_provider=spec.provides,
        )
        if provider_inner_spec.scope.level > spec.scope.level:
            msg = (
                "Provider dependency scope mismatch: "
                f"{dependency.provides!r} in provider {spec.provides!r} (scope "
                f"level {spec.scope.level}) cannot bind deeper dependency "
                f"{provider_inner_key!r} (scope level {provider_inner_spec.scope.level})."
            )
            raise DIWireInvalidProviderSpecError(msg)
        provider_is_async = is_async_provider_annotation(dependency.provides)
        provider_expression = (
            f"lambda: self.aresolve_{provider_inner_spec.slot}()"
            if provider_is_async
            else f"lambda: self.resolve_{provider_inner_spec.slot}()"
        )
        plan = ProviderDependencyPlan(
            kind="provider_handle",
            dependency=dependency,
            dependency_index=dependency_index,
            dependency_slot=None,
            dependency_requires_async=False,
            provider_inner_slot=provider_inner_spec.slot,
            provider_is_async=provider_is_async,
        )
        argument = self._format_dependency_argument_for_expression(
            dependency=dependency,
            expression=provider_expression,
        )
        return plan, None, False, argument, argument

    def _plan_all_dependency(
        self,
        *,
        dependency_index: int,
        dependency: ProviderDependency,
        dependency_key: Any,
    ) -> tuple[ProviderDependencyPlan, int | None, bool, str, str]:
        if dependency.parameter.kind is inspect.Parameter.VAR_KEYWORD:
            msg = (
                "All[...] dependencies are not supported for **kwargs parameters "
                f"({dependency.parameter.name!r}): All resolves to a tuple, which cannot "
                "be expanded as a mapping."
            )
            raise DIWireInvalidProviderSpecError(msg)
        inner = strip_all_annotation(dependency_key)
        slots = self._all_slots_by_key.get(inner, ())
        requires_async = any(self._requires_async_by_slot[slot] for slot in slots)
        plan = ProviderDependencyPlan(
            kind="all",
            dependency=dependency,
            dependency_index=dependency_index,
            dependency_slot=None,
            dependency_requires_async=requires_async,
            all_slots=slots,
        )
        sync_expression = self._format_all_dependency_expression(
            slots=slots,
            is_async_call=False,
        )
        async_expression = self._format_all_dependency_expression(
            slots=slots,
            is_async_call=True,
        )
        sync_argument = self._format_dependency_argument_for_expression(
            dependency=dependency,
            expression=sync_expression,
        )
        async_argument = self._format_dependency_argument_for_expression(
            dependency=dependency,
            expression=async_expression,
        )
        return plan, None, requires_async, sync_argument, async_argument

    def _plan_provider_dependency(
        self,
        *,
        spec: ProviderSpec,
        dependency_index: int,
        dependency: ProviderDependency,
        dependency_key: Any,
        optional: bool,
    ) -> tuple[ProviderDependencyPlan, int | None, bool, str, str]:
        dependency_spec = self._registrations.find_by_type(dependency_key)
        if dependency_spec is None and optional:
            if dependency.parameter.default is not inspect.Parameter.empty:
                omit_plan = ProviderDependencyPlan(
                    kind="omit",
                    dependency=dependency,
                    dependency_index=dependency_index,
                )
                return omit_plan, None, False, "", ""
            literal_expression = self._missing_optional_literal_expression(dependency=dependency)
            literal_plan = ProviderDependencyPlan(
                kind="literal",
                dependency=dependency,
                dependency_index=dependency_index,
                literal_expression=literal_expression,
            )
            argument = self._format_dependency_argument_for_expression(
                dependency=dependency,
                expression=literal_expression,
            )
            return literal_plan, None, False, argument, argument
        if dependency_spec is None:
            dependency_spec = self._dependency_spec_or_error(
                dependency_provides=dependency_key,
                requiring_provider=spec.provides,
            )
        requires_async = self._requires_async_by_slot[dependency_spec.slot]
        plan = ProviderDependencyPlan(
            kind="provider",
            dependency=dependency,
            dependency_index=dependency_index,
            dependency_slot=dependency_spec.slot,
            dependency_requires_async=requires_async,
        )
        sync_argument = self._format_dependency_argument(
            dependency=dependency,
            dependency_slot=dependency_spec.slot,
            dependency_requires_async=requires_async,
            is_async_call=False,
        )
        async_argument = self._format_dependency_argument(
            dependency=dependency,
            dependency_slot=dependency_spec.slot,
            dependency_requires_async=requires_async,
            is_async_call=True,
        )
        return plan, dependency_spec.slot, requires_async, sync_argument, async_argument

    def _split_maybe_dependency(self, dependency_provides: Any) -> tuple[bool, Any]:
        if not is_maybe_annotation(dependency_provides):
            return False, dependency_provides
        return True, strip_maybe_annotation(dependency_provides)

    def _missing_optional_literal_expression(self, *, dependency: ProviderDependency) -> str:
        parameter_kind = dependency.parameter.kind
        if parameter_kind is inspect.Parameter.VAR_POSITIONAL:
            return "()"
        if parameter_kind is inspect.Parameter.VAR_KEYWORD:
            return "{}"
        return "None"

    def _resolve_dispatch_kind(self, *, provides: Any) -> DispatchKind:
        if is_runtime_class(provides):
            return "identity"
        return "equality_map"

    def _resolve_effective_lock_mode(
        self,
        *,
        lock_mode: LockMode | Literal["auto"],
        has_async_specs: bool,
    ) -> LockMode:
        if lock_mode == "auto":
            if has_async_specs:
                return LockMode.ASYNC
            return LockMode.THREAD
        return lock_mode

    def _resolve_provider_attribute(self, *, spec: ProviderSpec) -> str:
        if spec.instance is not None:
            return "instance"
        if spec.concrete_type is not None:
            return "concrete_type"
        if spec.factory is not None:
            return "factory"
        if spec.generator is not None:
            return "generator"
        if spec.context_manager is not None:
            return "context_manager"

        msg = (
            f"Provider spec for slot {spec.slot} does not define a provider "
            "(instance, concrete_type, factory, generator, or context_manager)."
        )
        raise DIWireInvalidProviderSpecError(msg)

    def _is_cached(self, *, spec: ProviderSpec) -> bool:
        if spec.instance is not None:
            return True
        return spec.lifetime is not Lifetime.TRANSIENT

    def _cache_owner_scope_level(
        self,
        *,
        spec: ProviderSpec,
        is_cached: bool,
    ) -> int | None:
        if not is_cached:
            return None
        if spec.instance is not None:
            return self._root_scope.level
        if spec.lifetime is Lifetime.SCOPED:
            return spec.scope.level
        msg = f"Cannot resolve cache owner for provider slot {spec.slot}: {spec.lifetime!r}."
        raise DIWireInvalidProviderSpecError(msg)

    def _build_requires_async_by_slot(self) -> dict[int, bool]:
        by_slot = {spec.slot: spec for spec in self._work_specs}
        requires_async_by_slot: dict[int, bool] = {}
        in_progress: set[int] = set()

        for slot in by_slot:
            self._resolve_requires_async(
                slot=slot,
                by_slot=by_slot,
                requires_async_by_slot=requires_async_by_slot,
                in_progress=in_progress,
            )

        return requires_async_by_slot

    def _resolve_requires_async(
        self,
        *,
        slot: int,
        by_slot: dict[int, ProviderSpec],
        requires_async_by_slot: dict[int, bool],
        in_progress: set[int],
    ) -> bool:
        known = requires_async_by_slot.get(slot)
        if known is not None:
            return known

        if slot in in_progress:
            msg = f"Circular dependency detected while planning provider slot {slot}."
            raise DIWireInvalidProviderSpecError(msg)

        in_progress.add(slot)
        spec = by_slot[slot]

        requires_async = spec.is_async
        if not requires_async:
            for dependency in spec.dependencies:
                for dependency_slot in self._dependency_slots_for_graph(
                    dependency=dependency,
                    requiring_provider=spec.provides,
                ):
                    if self._resolve_requires_async(
                        slot=dependency_slot,
                        by_slot=by_slot,
                        requires_async_by_slot=requires_async_by_slot,
                        in_progress=in_progress,
                    ):
                        requires_async = True
                        break
                if requires_async:
                    break

        in_progress.remove(slot)
        requires_async_by_slot[slot] = requires_async
        return requires_async

    def _dependency_slots_for_graph(
        self,
        *,
        dependency: ProviderDependency,
        requiring_provider: Any,
    ) -> tuple[int, ...]:
        optional, dependency_key = self._split_maybe_dependency(dependency.provides)
        if is_from_context_annotation(dependency_key) or is_provider_annotation(
            dependency_key,
        ):
            return ()
        if is_all_annotation(dependency_key):
            inner = strip_all_annotation(dependency_key)
            return self._all_slots_by_key.get(inner, ())
        if optional:
            dependency_spec = self._registrations.find_by_type(dependency_key)
            if dependency_spec is None:
                return ()
            return (dependency_spec.slot,)
        dependency_spec = self._dependency_spec_or_error(
            dependency_provides=dependency_key,
            requiring_provider=requiring_provider,
        )
        return (dependency_spec.slot,)

    def _format_dependency_argument(
        self,
        *,
        dependency: ProviderDependency,
        dependency_slot: int,
        dependency_requires_async: bool,
        is_async_call: bool,
    ) -> str:
        expression = self._dependency_expression(
            dependency_slot=dependency_slot,
            dependency_requires_async=dependency_requires_async,
            is_async_call=is_async_call,
        )
        return self._format_dependency_argument_for_expression(
            dependency=dependency,
            expression=expression,
        )

    def _format_dependency_argument_for_expression(
        self,
        *,
        dependency: ProviderDependency,
        expression: str,
    ) -> str:
        """Format dependency value expression according to original parameter shape."""
        kind = dependency.parameter.kind
        if kind is inspect.Parameter.POSITIONAL_ONLY:
            return expression
        if kind is inspect.Parameter.VAR_POSITIONAL:
            return f"*{expression}"
        if kind is inspect.Parameter.VAR_KEYWORD:
            return f"**{expression}"
        parameter_name = dependency.parameter.name
        if not parameter_name.isidentifier() or keyword.iskeyword(parameter_name):
            msg = (
                f"Dependency parameter name '{parameter_name}' "
                "is not a valid identifier for generated keyword-argument wiring."
            )
            raise DIWireInvalidProviderSpecError(msg)
        return f"{parameter_name}={expression}"

    def _dependency_expression(
        self,
        *,
        dependency_slot: int,
        dependency_requires_async: bool,
        is_async_call: bool,
    ) -> str:
        if is_async_call and dependency_requires_async:
            return f"await self.aresolve_{dependency_slot}()"
        return f"self.resolve_{dependency_slot}()"

    def _format_all_dependency_expression(
        self,
        *,
        slots: tuple[int, ...],
        is_async_call: bool,
    ) -> str:
        if not slots:
            return "()"
        expressions = [
            self._dependency_expression(
                dependency_slot=slot,
                dependency_requires_async=self._requires_async_by_slot[slot],
                is_async_call=is_async_call,
            )
            for slot in slots
        ]
        return f"({', '.join(expressions)},)"

    def _dependency_order_is_signature_order(self, *, spec: ProviderSpec) -> bool:
        if not spec.dependencies:
            return True

        provider_callable = self._provider_callable_for_signature(spec=spec)
        if provider_callable is None:
            return False

        parameters = list(inspect.signature(provider_callable).parameters.values())
        if spec.concrete_type is not None and parameters:
            parameters = parameters[1:]

        order_by_name = {parameter.name: index for index, parameter in enumerate(parameters)}
        last_index = -1
        for dependency in spec.dependencies:
            current_index = order_by_name.get(dependency.parameter.name)
            if current_index is None or current_index < last_index:
                return False
            last_index = current_index
        return True

    def _provider_callable_for_signature(self, *, spec: ProviderSpec) -> Any | None:
        if spec.concrete_type is not None:
            return spec.concrete_type.__init__
        if spec.factory is not None:
            return spec.factory
        if spec.generator is not None:
            return spec.generator
        if spec.context_manager is not None:
            return spec.context_manager
        return None

    def _build_max_required_scope_level_by_slot(self) -> dict[int, int]:
        by_slot = {spec.slot: spec for spec in self._work_specs}
        max_scope_level_by_slot: dict[int, int] = {}
        in_progress: set[int] = set()

        for slot in by_slot:
            self._resolve_max_required_scope_level(
                slot=slot,
                by_slot=by_slot,
                max_scope_level_by_slot=max_scope_level_by_slot,
                in_progress=in_progress,
            )

        return max_scope_level_by_slot

    def _resolve_max_required_scope_level(
        self,
        *,
        slot: int,
        by_slot: dict[int, ProviderSpec],
        max_scope_level_by_slot: dict[int, int],
        in_progress: set[int],
    ) -> int:
        known = max_scope_level_by_slot.get(slot)
        if known is not None:
            return known

        if slot in in_progress:
            msg = f"Circular dependency detected while planning provider slot {slot}."
            raise DIWireInvalidProviderSpecError(msg)

        in_progress.add(slot)
        spec = by_slot[slot]
        max_scope_level = spec.scope.level

        for dependency in spec.dependencies:
            for dependency_slot in self._dependency_slots_for_graph(
                dependency=dependency,
                requiring_provider=spec.provides,
            ):
                dependency_max_scope = self._resolve_max_required_scope_level(
                    slot=dependency_slot,
                    by_slot=by_slot,
                    max_scope_level_by_slot=max_scope_level_by_slot,
                    in_progress=in_progress,
                )
                max_scope_level = max(max_scope_level, dependency_max_scope)

        in_progress.remove(slot)
        max_scope_level_by_slot[slot] = max_scope_level
        return max_scope_level

    def _dependency_spec_or_error(
        self,
        *,
        dependency_provides: Any,
        requiring_provider: Any,
    ) -> ProviderSpec:
        try:
            return self._registrations.get_by_type(dependency_provides)
        except KeyError as error:
            msg = (
                f"Dependency {dependency_provides!r} required by provider "
                f"{requiring_provider!r} is not registered."
            )
            raise DIWireDependencyNotRegisteredError(msg) from error

    def _build_all_slots_by_key(self) -> dict[Any, tuple[int, ...]]:
        slots_by_key: dict[Any, list[int]] = {}
        for spec in self._work_specs:
            base_key = component_base_key(spec.provides)
            if base_key is None:
                if getattr(spec.provides, "__metadata__", None) is not None:
                    continue
                base_key = spec.provides
            slots_by_key.setdefault(base_key, []).append(spec.slot)
        return {key: tuple(slots) for key, slots in slots_by_key.items()}
