from __future__ import annotations

import inspect
from dataclasses import dataclass
from enum import Enum

from diwire.exceptions import DIWireInvalidProviderSpecError
from diwire.providers import Lifetime, ProviderDependency, ProviderSpec, ProvidersRegistrations
from diwire.scope import BaseScope


class LockMode(Enum):
    """Locking strategy used by generated resolvers."""

    THREAD = "thread"
    ASYNC = "async"


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
class ProviderWorkflowPlan:
    """Provider metadata used during method rendering."""

    slot: int
    provider_attribute: str
    scope_level: int
    scope_attr_name: str
    is_cached: bool
    is_transient: bool
    cache_owner_scope_level: int | None
    concurrency_safe: bool
    is_provider_async: bool
    requires_async: bool
    needs_cleanup: bool
    sync_arguments: tuple[str, ...]
    async_arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolverGenerationPlan:
    """Deterministic plan consumed by the renderer."""

    root_scope_level: int
    lock_mode: LockMode
    has_cleanup: bool
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
        self._work_specs = self._collect_specs()
        self._requires_async_by_slot = self._build_requires_async_by_slot()

    def build(self) -> ResolverGenerationPlan:
        """Build resolver generation metadata."""
        # Design contract:
        # - generated runtime stays class-first (RootResolver + scope resolver classes),
        # - cached providers use method replacement (lambda/async def),
        # - hot path avoids reflective dispatch or dynamic attribute lookup helpers.
        scopes = self._build_scope_plans()
        scope_by_level = {scope.scope_level: scope for scope in scopes}

        workflows = tuple(
            self._build_workflow_plan(spec=spec, scope_by_level=scope_by_level)
            for spec in self._work_specs
        )

        has_async_specs = any(spec.is_async for spec in self._work_specs)
        has_cleanup = any(spec.needs_cleanup for spec in self._work_specs)

        return ResolverGenerationPlan(
            root_scope_level=self._root_scope.level,
            lock_mode=LockMode.ASYNC if has_async_specs else LockMode.THREAD,
            has_cleanup=has_cleanup,
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
        scopes_owner = self._root_scope.owner()
        managed_scopes = [scope for scope in scopes_owner if scope.level >= self._root_scope.level]
        ordered_scopes = sorted(managed_scopes, key=lambda scope: scope.level)

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
                    resolver_arg_name=f"{scope_name}_resolver",
                    resolver_attr_name=f"_{scope_name}_resolver",
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
    ) -> ProviderWorkflowPlan:
        provider_attribute = self._resolve_provider_attribute(spec=spec)
        is_cached = self._is_cached(spec=spec)
        cache_owner_scope_level = self._cache_owner_scope_level(spec=spec, is_cached=is_cached)

        dependency_specs = [
            self._registrations.get_by_type(dependency.provides) for dependency in spec.dependencies
        ]

        sync_arguments = tuple(
            self._format_dependency_argument(
                dependency=dependency,
                dependency_slot=dependency_spec.slot,
                dependency_requires_async=self._requires_async_by_slot[dependency_spec.slot],
                is_async_call=False,
            )
            for dependency, dependency_spec in zip(spec.dependencies, dependency_specs, strict=True)
        )
        async_arguments = tuple(
            self._format_dependency_argument(
                dependency=dependency,
                dependency_slot=dependency_spec.slot,
                dependency_requires_async=self._requires_async_by_slot[dependency_spec.slot],
                is_async_call=True,
            )
            for dependency, dependency_spec in zip(spec.dependencies, dependency_specs, strict=True)
        )

        scope_plan = scope_by_level[spec.scope.level]
        return ProviderWorkflowPlan(
            slot=spec.slot,
            provider_attribute=provider_attribute,
            scope_level=scope_plan.scope_level,
            scope_attr_name=scope_plan.resolver_attr_name,
            is_cached=is_cached,
            is_transient=not is_cached,
            cache_owner_scope_level=cache_owner_scope_level,
            concurrency_safe=spec.concurrency_safe,
            is_provider_async=spec.is_async,
            requires_async=self._requires_async_by_slot[spec.slot],
            needs_cleanup=spec.needs_cleanup,
            sync_arguments=sync_arguments,
            async_arguments=async_arguments,
        )

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
        if spec.lifetime is Lifetime.TRANSIENT:
            return False
        if spec.lifetime is Lifetime.SINGLETON:
            return True
        return spec.lifetime is Lifetime.SCOPED

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
        if spec.lifetime is Lifetime.SINGLETON:
            return self._root_scope.level
        if spec.lifetime is Lifetime.SCOPED:
            return spec.scope.level
        return self._root_scope.level

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
                dependency_spec = self._registrations.get_by_type(dependency.provides)
                if self._resolve_requires_async(
                    slot=dependency_spec.slot,
                    by_slot=by_slot,
                    requires_async_by_slot=requires_async_by_slot,
                    in_progress=in_progress,
                ):
                    requires_async = True
                    break

        in_progress.remove(slot)
        requires_async_by_slot[slot] = requires_async
        return requires_async

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

        kind = dependency.parameter.kind
        if kind is inspect.Parameter.POSITIONAL_ONLY:
            return expression
        if kind is inspect.Parameter.VAR_POSITIONAL:
            return f"*{expression}"
        if kind is inspect.Parameter.VAR_KEYWORD:
            return f"**{expression}"
        return f"{dependency.parameter.name}={expression}"

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
