from __future__ import annotations

from dataclasses import dataclass
from textwrap import indent

from jinja2 import Environment, Template

from diwire.providers import ProvidersRegistrations
from diwire.resolvers.templates.planner import (
    LockMode,
    ProviderWorkflowPlan,
    ResolverGenerationPlan,
    ResolverGenerationPlanner,
    ScopePlan,
)
from diwire.resolvers.templates.templates import (
    ASYNC_METHOD_TEMPLATE,
    BUILD_FUNCTION_TEMPLATE,
    CLASS_TEMPLATE,
    CONTEXT_AENTER_METHOD_TEMPLATE,
    CONTEXT_AEXIT_NO_CLEANUP_TEMPLATE,
    CONTEXT_AEXIT_WITH_CLEANUP_TEMPLATE,
    CONTEXT_ENTER_METHOD_TEMPLATE,
    CONTEXT_EXIT_NO_CLEANUP_TEMPLATE,
    CONTEXT_EXIT_WITH_CLEANUP_TEMPLATE,
    DISPATCH_ARESOLVE_METHOD_TEMPLATE,
    DISPATCH_RESOLVE_METHOD_TEMPLATE,
    ENTER_SCOPE_METHOD_TEMPLATE,
    GLOBALS_TEMPLATE,
    IMPORTS_TEMPLATE,
    INIT_METHOD_TEMPLATE,
    MODULE_TEMPLATE,
    SYNC_METHOD_TEMPLATE,
)
from diwire.scope import BaseScope, BaseScopes, Scope

_INDENT = " " * 4


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Context for rendering resolver templates."""

    root_scope: BaseScope
    scopes: type[BaseScopes]
    registrations: ProvidersRegistrations


class ResolversTemplateRenderer:
    """Renderer for generated resolver code."""

    def __init__(self) -> None:
        self._env = Environment(autoescape=False)  # noqa: S701
        self._module_template = self._template(MODULE_TEMPLATE)
        self._imports_template = self._template(IMPORTS_TEMPLATE)
        self._globals_template = self._template(GLOBALS_TEMPLATE)
        self._class_template = self._template(CLASS_TEMPLATE)
        self._init_method_template = self._template(INIT_METHOD_TEMPLATE)
        self._enter_scope_method_template = self._template(ENTER_SCOPE_METHOD_TEMPLATE)
        self._resolve_dispatch_template = self._template(DISPATCH_RESOLVE_METHOD_TEMPLATE)
        self._aresolve_dispatch_template = self._template(DISPATCH_ARESOLVE_METHOD_TEMPLATE)
        self._sync_method_template = self._template(SYNC_METHOD_TEMPLATE)
        self._async_method_template = self._template(ASYNC_METHOD_TEMPLATE)
        self._build_function_template = self._template(BUILD_FUNCTION_TEMPLATE)

    def get_providers_code(
        self,
        *,
        root_scope: BaseScope,
        registrations: ProvidersRegistrations,
    ) -> str:
        """Render generated resolver code for the current registrations."""
        # Design contract mirrored from planner:
        # emit class-based direct-call runtime with method-replacement caches and no reflective hot path.
        _ = RenderContext(
            root_scope=root_scope,
            scopes=root_scope.owner,
            registrations=registrations,
        )
        plan = ResolverGenerationPlanner(
            root_scope=root_scope,
            registrations=registrations,
        ).build()

        imports_block = self._render_imports(plan=plan)
        globals_block = self._render_globals(plan=plan)
        classes_block = self._render_classes(plan=plan)
        build_block = self._render_build_function(plan=plan)

        return self._module_template.render(
            imports_block=imports_block,
            globals_block=globals_block,
            classes_block=classes_block,
            build_block=build_block,
        )

    def _render_imports(self, *, plan: ResolverGenerationPlan) -> str:
        uses_generator_context_helpers = any(
            workflow.provider_attribute == "generator" for workflow in plan.workflows
        )
        return self._imports_template.render(
            lock_mode=plan.lock_mode.value,
            uses_generator_context_helpers=uses_generator_context_helpers,
        ).strip()

    def _render_globals(self, *, plan: ResolverGenerationPlan) -> str:
        provider_lines: list[str] = []
        for workflow in plan.workflows:
            provider_lines.extend(
                [
                    f"_dep_{workflow.slot}_type: Any = _MISSING_PROVIDER",
                    f"_provider_{workflow.slot}: Any = _MISSING_PROVIDER",
                ],
            )

        lock_lines: list[str] = []
        for workflow in plan.workflows:
            if not workflow.is_cached or not workflow.concurrency_safe:
                continue
            if plan.lock_mode is LockMode.THREAD:
                lock_lines.append(f"_dep_{workflow.slot}_thread_lock = threading.Lock()")
            elif workflow.requires_async:
                lock_lines.append(f"_dep_{workflow.slot}_async_lock = asyncio.Lock()")

        return self._globals_template.render(
            provider_globals_block="\n".join(provider_lines),
            lock_globals_block="\n".join(lock_lines),
        ).strip()

    def _render_classes(self, *, plan: ResolverGenerationPlan) -> str:
        scope_by_level = {scope.scope_level: scope for scope in plan.scopes}
        class_blocks = [
            self._render_class(
                plan=plan,
                class_plan=class_plan,
                scope_by_level=scope_by_level,
            )
            for class_plan in plan.scopes
        ]
        return "\n\n\n".join(class_blocks)

    def _render_class(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
        scope_by_level: dict[int, ScopePlan],
    ) -> str:
        init_method_block = self._indent_block(
            self._render_init_method(plan=plan, class_plan=class_plan),
        )
        enter_scope_method_block = self._indent_block(
            self._render_enter_scope_method(plan=plan, class_plan=class_plan),
        )
        resolve_method_block = self._indent_block(self._render_dispatch_resolve_method(plan=plan))
        aresolve_method_block = self._indent_block(
            self._render_dispatch_aresolve_method(plan=plan),
        )

        if plan.has_cleanup:
            exit_method_block = self._indent_block(CONTEXT_EXIT_WITH_CLEANUP_TEMPLATE)
            aexit_method_block = self._indent_block(CONTEXT_AEXIT_WITH_CLEANUP_TEMPLATE)
        else:
            exit_method_block = self._indent_block(CONTEXT_EXIT_NO_CLEANUP_TEMPLATE)
            aexit_method_block = self._indent_block(CONTEXT_AEXIT_NO_CLEANUP_TEMPLATE)

        resolver_methods: list[str] = []
        for workflow in plan.workflows:
            resolver_methods.append(
                self._render_sync_method(
                    plan=plan,
                    class_plan=class_plan,
                    scope_by_level=scope_by_level,
                    workflow=workflow,
                ),
            )
            resolver_methods.append(
                self._render_async_method(
                    plan=plan,
                    class_plan=class_plan,
                    scope_by_level=scope_by_level,
                    workflow=workflow,
                ),
            )

        resolver_methods_block = "\n\n".join(
            self._indent_block(method) for method in resolver_methods
        )
        return self._class_template.render(
            class_name=class_plan.class_name,
            init_method_block=init_method_block,
            enter_scope_method_block=enter_scope_method_block,
            resolve_method_block=resolve_method_block,
            aresolve_method_block=aresolve_method_block,
            enter_method_block=self._indent_block(CONTEXT_ENTER_METHOD_TEMPLATE),
            exit_method_block=exit_method_block,
            aenter_method_block=self._indent_block(CONTEXT_AENTER_METHOD_TEMPLATE),
            aexit_method_block=aexit_method_block,
            resolver_methods_block=resolver_methods_block,
        ).strip()

    def _render_init_method(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
    ) -> str:
        signature_lines = self._build_init_signature_lines(
            plan=plan,
            class_plan=class_plan,
        )
        body_lines = self._build_init_body_lines(
            plan=plan,
            class_plan=class_plan,
        )
        return self._init_method_template.render(
            signature_block=self._join_lines(self._indent_lines(signature_lines, 1)),
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _build_init_signature_lines(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
    ) -> list[str]:
        if class_plan.is_root:
            return ["cleanup_enabled: bool = True,"]

        if self._uses_stateless_scope_reuse(plan=plan):
            return [
                "root_resolver: RootResolver,",
                "cleanup_enabled: bool = True,",
            ]

        ancestor_lines = [
            f"{scope.resolver_arg_name}: Any = _MISSING_RESOLVER,"
            for scope in self._ancestor_non_root_scopes(
                plan=plan,
                scope_level=class_plan.scope_level,
            )
        ]
        return [
            "root_resolver: RootResolver,",
            "cleanup_enabled: bool = True,",
            *ancestor_lines,
        ]

    def _build_init_body_lines(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
    ) -> list[str]:
        body_lines = [
            f"self._scope_level = {class_plan.scope_level}",
            "self._cleanup_enabled = cleanup_enabled",
        ]
        if class_plan.is_root:
            body_lines.append("self._root_resolver = self")
        else:
            body_lines.append("self._root_resolver = root_resolver")

        if plan.has_cleanup:
            body_lines.append("self._cleanup_callbacks: list[tuple[int, Any]] = []")

        body_lines.append(f"self.{plan.scopes[0].resolver_attr_name} = self._root_resolver")

        uses_stateless_scope_reuse = self._uses_stateless_scope_reuse(plan=plan)
        if not uses_stateless_scope_reuse:
            for scope in self._stored_non_root_scopes(
                plan=plan,
                class_scope_level=class_plan.scope_level,
            ):
                if scope.scope_level == class_plan.scope_level:
                    body_lines.append(f"self.{scope.resolver_attr_name} = self")
                else:
                    body_lines.append(
                        f"self.{scope.resolver_attr_name} = {scope.resolver_arg_name}",
                    )

        if uses_stateless_scope_reuse and class_plan.is_root:
            for scope in plan.scopes:
                if scope.is_root:
                    continue
                body_lines.append(
                    f"self._scope_resolver_{scope.scope_level} = {scope.class_name}("
                    "self._root_resolver, self._cleanup_enabled)",
                )

        body_lines.extend(
            f"self._cache_{workflow.slot} = _MISSING_CACHE"
            for workflow in plan.workflows
            if workflow.is_cached and workflow.cache_owner_scope_level == class_plan.scope_level
        )
        return body_lines

    def _render_enter_scope_method(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
    ) -> str:
        immediate_next, default_next, explicit_candidates = self._next_scope_options(
            plan=plan,
            class_scope_level=class_plan.scope_level,
        )
        if immediate_next is None:
            return self._enter_scope_method_template.render(
                body_block=self._join_lines(
                    self._indent_lines(
                        [
                            'msg = f"Cannot enter deeper scope from level {self._scope_level}."',
                            "raise DIWireScopeMismatchError(msg)",
                        ],
                        1,
                    ),
                ),
            ).strip()

        if default_next is None:
            msg = "Expected a default scope transition but none was found."
            raise ValueError(msg)

        body_lines = [
            "if scope is None:",
            *self._indent_lines(
                self._constructor_return_lines(
                    plan=plan,
                    current_scope_level=class_plan.scope_level,
                    target_scope=default_next,
                ),
                1,
            ),
        ]

        body_lines.extend(
            [
                "target_scope_level = scope.level",
                "if target_scope_level == self._scope_level:",
                "    return self",
                "if target_scope_level <= self._scope_level:",
                (
                    '    msg = f"Cannot enter scope level {target_scope_level} from level '
                    '{self._scope_level}."'
                ),
                "    raise DIWireScopeMismatchError(msg)",
            ],
        )

        for candidate in explicit_candidates:
            body_lines.append(f"if target_scope_level == {candidate.scope_level}:")
            body_lines.extend(
                self._indent_lines(
                    self._constructor_return_lines(
                        plan=plan,
                        current_scope_level=class_plan.scope_level,
                        target_scope=candidate,
                    ),
                    1,
                ),
            )

        body_lines.extend(
            [
                (
                    'msg = f"Scope level {target_scope_level} is not a valid next transition '
                    'from level {self._scope_level}."'
                ),
                "raise DIWireScopeMismatchError(msg)",
            ],
        )
        return self._enter_scope_method_template.render(
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _constructor_return_lines(
        self,
        *,
        plan: ResolverGenerationPlan,
        current_scope_level: int,
        target_scope: ScopePlan,
    ) -> list[str]:
        if self._uses_stateless_scope_reuse(plan=plan):
            return [f"return self._root_resolver._scope_resolver_{target_scope.scope_level}"]

        arguments = ["self._root_resolver", "self._cleanup_enabled"]
        for ancestor in self._ancestor_non_root_scopes(
            plan=plan,
            scope_level=target_scope.scope_level,
        ):
            if ancestor.scope_level < current_scope_level:
                arguments.append(f"self.{ancestor.resolver_attr_name}")
            elif ancestor.scope_level == current_scope_level:
                arguments.append("self")
            else:
                arguments.append("_MISSING_RESOLVER")

        lines = [f"return {target_scope.class_name}("]
        lines.extend(f"    {argument}," for argument in arguments)
        lines.append(")")
        return lines

    def _next_scope_options(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_scope_level: int,
    ) -> tuple[ScopePlan | None, ScopePlan | None, tuple[ScopePlan, ...]]:
        deeper_scopes = [scope for scope in plan.scopes if scope.scope_level > class_scope_level]
        if not deeper_scopes:
            return None, None, ()

        immediate_next = deeper_scopes[0]
        default_next = next(
            (scope for scope in deeper_scopes if not scope.skippable),
            immediate_next,
        )
        explicit_candidates: list[ScopePlan] = [immediate_next]
        if immediate_next.skippable and default_next.scope_level != immediate_next.scope_level:
            explicit_candidates.append(default_next)
        return immediate_next, default_next, tuple(explicit_candidates)

    def _render_dispatch_resolve_method(self, *, plan: ResolverGenerationPlan) -> str:
        body_lines: list[str] = []
        for workflow in plan.workflows:
            body_lines.extend(
                [
                    f"if dependency is _dep_{workflow.slot}_type:",
                    f"    return self.resolve_{workflow.slot}()",
                ],
            )
        body_lines.extend(
            [
                'msg = f"Dependency {dependency!r} is not registered."',
                "raise DIWireDependencyNotRegisteredError(msg)",
            ],
        )
        return self._resolve_dispatch_template.render(
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _render_dispatch_aresolve_method(self, *, plan: ResolverGenerationPlan) -> str:
        body_lines: list[str] = []
        for workflow in plan.workflows:
            body_lines.extend(
                [
                    f"if dependency is _dep_{workflow.slot}_type:",
                    f"    return await self.aresolve_{workflow.slot}()",
                ],
            )
        body_lines.extend(
            [
                'msg = f"Dependency {dependency!r} is not registered."',
                "raise DIWireDependencyNotRegisteredError(msg)",
            ],
        )
        return self._aresolve_dispatch_template.render(
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _render_sync_method(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
        scope_by_level: dict[int, ScopePlan],
        workflow: ProviderWorkflowPlan,
    ) -> str:
        owner_scope_level = workflow.cache_owner_scope_level
        if (
            workflow.is_cached
            and owner_scope_level is not None
            and owner_scope_level != class_plan.scope_level
        ):
            if owner_scope_level > class_plan.scope_level:
                body_lines = self._scope_mismatch_lines(workflow=workflow)
            else:
                owner_scope = scope_by_level[owner_scope_level]
                body_lines = self._render_owner_guard(
                    workflow=workflow,
                    scope_attr_name=owner_scope.resolver_attr_name,
                    resolver_name="owner_resolver",
                )
                body_lines.append(f"return owner_resolver.resolve_{workflow.slot}()")
            return self._sync_method_template.render(
                slot=workflow.slot,
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        body_lines = self._render_provider_scope_guard(
            class_scope_level=class_plan.scope_level,
            scope_by_level=scope_by_level,
            workflow=workflow,
        )
        if workflow.requires_async:
            body_lines.extend(
                [
                    f'msg = "Provider slot {workflow.slot} requires asynchronous resolution."',
                    "raise DIWireAsyncDependencyInSyncContextError(msg)",
                ],
            )
            return self._sync_method_template.render(
                slot=workflow.slot,
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        if workflow.is_cached:
            body_lines.extend(
                [
                    f"cached_value = self._cache_{workflow.slot}",
                    "if cached_value is not _MISSING_CACHE:",
                    "    return cached_value",
                ],
            )

        uses_thread_lock = (
            workflow.is_cached and workflow.concurrency_safe and plan.lock_mode is LockMode.THREAD
        )
        if uses_thread_lock:
            body_lines.append(f"with _dep_{workflow.slot}_thread_lock:")
            body_lines.extend(
                self._indent_lines(
                    [
                        f"cached_value = self._cache_{workflow.slot}",
                        "if cached_value is not _MISSING_CACHE:",
                        "    return cached_value",
                        *self._render_local_value_build(
                            workflow=workflow,
                            is_async_call=False,
                        ),
                        *self._render_sync_cache_replace(workflow=workflow),
                        "return value",
                    ],
                    1,
                ),
            )
            return self._sync_method_template.render(
                slot=workflow.slot,
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        body_lines.extend(
            [
                *self._render_local_value_build(
                    workflow=workflow,
                    is_async_call=False,
                ),
                *self._render_sync_cache_replace(workflow=workflow),
                "return value",
            ],
        )
        return self._sync_method_template.render(
            slot=workflow.slot,
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _render_async_method(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
        scope_by_level: dict[int, ScopePlan],
        workflow: ProviderWorkflowPlan,
    ) -> str:
        if not workflow.requires_async:
            return self._async_method_template.render(
                slot=workflow.slot,
                body_block=self._join_lines(
                    self._indent_lines([f"return self.resolve_{workflow.slot}()"], 1),
                ),
            ).strip()

        owner_scope_level = workflow.cache_owner_scope_level
        if (
            workflow.is_cached
            and owner_scope_level is not None
            and owner_scope_level != class_plan.scope_level
        ):
            if owner_scope_level > class_plan.scope_level:
                body_lines = self._scope_mismatch_lines(workflow=workflow)
            else:
                owner_scope = scope_by_level[owner_scope_level]
                body_lines = self._render_owner_guard(
                    workflow=workflow,
                    scope_attr_name=owner_scope.resolver_attr_name,
                    resolver_name="owner_resolver",
                )
                body_lines.append(f"return await owner_resolver.aresolve_{workflow.slot}()")
            return self._async_method_template.render(
                slot=workflow.slot,
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        body_lines = self._render_provider_scope_guard(
            class_scope_level=class_plan.scope_level,
            scope_by_level=scope_by_level,
            workflow=workflow,
        )
        if workflow.is_cached:
            body_lines.extend(
                [
                    f"cached_value = self._cache_{workflow.slot}",
                    "if cached_value is not _MISSING_CACHE:",
                    "    return cached_value",
                ],
            )

        uses_async_lock = (
            workflow.is_cached and workflow.concurrency_safe and plan.lock_mode is LockMode.ASYNC
        )
        if uses_async_lock:
            body_lines.append(f"async with _dep_{workflow.slot}_async_lock:")
            body_lines.extend(
                self._indent_lines(
                    [
                        f"cached_value = self._cache_{workflow.slot}",
                        "if cached_value is not _MISSING_CACHE:",
                        "    return cached_value",
                        *self._render_local_value_build(
                            workflow=workflow,
                            is_async_call=True,
                        ),
                        *self._render_async_cache_replace(workflow=workflow),
                        "return value",
                    ],
                    1,
                ),
            )
            return self._async_method_template.render(
                slot=workflow.slot,
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        body_lines.extend(
            [
                *self._render_local_value_build(
                    workflow=workflow,
                    is_async_call=True,
                ),
                *self._render_async_cache_replace(workflow=workflow),
                "return value",
            ],
        )
        return self._async_method_template.render(
            slot=workflow.slot,
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _render_provider_scope_guard(
        self,
        *,
        class_scope_level: int,
        scope_by_level: dict[int, ScopePlan],
        workflow: ProviderWorkflowPlan,
    ) -> list[str]:
        if workflow.scope_level > class_scope_level:
            return self._scope_mismatch_lines(workflow=workflow)
        if workflow.scope_level == class_scope_level:
            return ["provider_scope_resolver = self"]
        scope = scope_by_level[workflow.scope_level]
        return [
            f"provider_scope_resolver = self.{scope.resolver_attr_name}",
            "if provider_scope_resolver is _MISSING_RESOLVER:",
            *self._indent_lines(self._scope_mismatch_lines(workflow=workflow), 1),
        ]

    def _render_owner_guard(
        self,
        *,
        workflow: ProviderWorkflowPlan,
        scope_attr_name: str,
        resolver_name: str,
    ) -> list[str]:
        return [
            f"{resolver_name} = self.{scope_attr_name}",
            f"if {resolver_name} is _MISSING_RESOLVER:",
            *self._indent_lines(self._scope_mismatch_lines(workflow=workflow), 1),
        ]

    def _scope_mismatch_lines(self, *, workflow: ProviderWorkflowPlan) -> list[str]:
        return [
            (
                f'msg = "Provider slot {workflow.slot} requires opened scope level '
                f'{workflow.scope_level}."'
            ),
            "raise DIWireScopeMismatchError(msg)",
        ]

    def _render_local_value_build(
        self,
        *,
        workflow: ProviderWorkflowPlan,
        is_async_call: bool,
    ) -> list[str]:
        arguments = workflow.async_arguments if is_async_call else workflow.sync_arguments
        provider_expr = f"_provider_{workflow.slot}"

        if workflow.provider_attribute == "instance":
            return [f"value = {provider_expr}"]

        if workflow.provider_attribute in {"concrete_type", "factory"}:
            lines = self._render_callable_call(
                variable_name="value",
                callable_expression=provider_expr,
                arguments=arguments,
            )
            if workflow.is_provider_async:
                lines.append("value = await value")
            return lines

        if workflow.provider_attribute == "generator":
            return self._render_generator_build(
                workflow=workflow,
                arguments=arguments,
                is_async_call=is_async_call,
            )

        if workflow.provider_attribute == "context_manager":
            return self._render_context_manager_build(
                workflow=workflow,
                arguments=arguments,
            )

        msg = f"Unsupported provider attribute {workflow.provider_attribute!r}."
        raise ValueError(msg)

    def _render_generator_build(
        self,
        *,
        workflow: ProviderWorkflowPlan,
        arguments: tuple[str, ...],
        is_async_call: bool,
    ) -> list[str]:
        if workflow.is_provider_async:
            if not is_async_call:
                msg = f"Async generator provider slot {workflow.slot} cannot be resolved synchronously."
                raise ValueError(msg)
            context_lines = self._render_callable_call(
                variable_name="_provider_cm",
                callable_expression=f"asynccontextmanager(_provider_{workflow.slot})",
                arguments=arguments,
            )
            generator_lines = self._render_callable_call(
                variable_name="_provider_gen",
                callable_expression=f"_provider_{workflow.slot}",
                arguments=arguments,
            )
            return [
                "if self._cleanup_enabled:",
                *self._indent_lines(
                    [
                        *context_lines,
                        "value = await _provider_cm.__aenter__()",
                        "provider_scope_resolver._cleanup_callbacks.append((1, _provider_cm.__aexit__))",
                    ],
                    1,
                ),
                "else:",
                *self._indent_lines(
                    [
                        *generator_lines,
                        "value = await anext(_provider_gen)",
                    ],
                    1,
                ),
            ]

        context_lines = self._render_callable_call(
            variable_name="_provider_cm",
            callable_expression=f"contextmanager(_provider_{workflow.slot})",
            arguments=arguments,
        )
        generator_lines = self._render_callable_call(
            variable_name="_provider_gen",
            callable_expression=f"_provider_{workflow.slot}",
            arguments=arguments,
        )
        return [
            "if self._cleanup_enabled:",
            *self._indent_lines(
                [
                    *context_lines,
                    "value = _provider_cm.__enter__()",
                    "provider_scope_resolver._cleanup_callbacks.append((0, _provider_cm.__exit__))",
                ],
                1,
            ),
            "else:",
            *self._indent_lines(
                [
                    *generator_lines,
                    "value = next(_provider_gen)",
                ],
                1,
            ),
        ]

    def _render_context_manager_build(
        self,
        *,
        workflow: ProviderWorkflowPlan,
        arguments: tuple[str, ...],
    ) -> list[str]:
        lines = self._render_callable_call(
            variable_name="_provider_cm",
            callable_expression=f"_provider_{workflow.slot}",
            arguments=arguments,
        )
        if workflow.is_provider_async:
            lines.extend(
                [
                    "value = await _provider_cm.__aenter__()",
                    "if self._cleanup_enabled:",
                    "    provider_scope_resolver._cleanup_callbacks.append((1, _provider_cm.__aexit__))",
                ],
            )
            return lines

        lines.extend(
            [
                "value = _provider_cm.__enter__()",
                "if self._cleanup_enabled:",
                "    provider_scope_resolver._cleanup_callbacks.append((0, _provider_cm.__exit__))",
            ],
        )
        return lines

    def _render_sync_cache_replace(self, *, workflow: ProviderWorkflowPlan) -> list[str]:
        if not workflow.is_cached:
            return []
        return [
            f"self._cache_{workflow.slot} = value",
            f"self.resolve_{workflow.slot} = lambda: value",
            "",
            "async def _cached() -> Any:",
            "    return value",
            "",
            f"self.aresolve_{workflow.slot} = _cached",
        ]

    def _render_async_cache_replace(self, *, workflow: ProviderWorkflowPlan) -> list[str]:
        if not workflow.is_cached:
            return []
        return [
            f"self._cache_{workflow.slot} = value",
            "",
            "async def _cached() -> Any:",
            "    return value",
            "",
            f"self.aresolve_{workflow.slot} = _cached",
        ]

    def _render_callable_call(
        self,
        *,
        variable_name: str,
        callable_expression: str,
        arguments: tuple[str, ...],
    ) -> list[str]:
        if not arguments:
            return [f"{variable_name} = {callable_expression}()"]
        lines = [f"{variable_name} = {callable_expression}("]
        lines.extend(f"    {argument}," for argument in arguments)
        lines.append(")")
        return lines

    def _render_build_function(self, *, plan: ResolverGenerationPlan) -> str:
        body_lines = [
            f"global _dep_{workflow.slot}_type, _provider_{workflow.slot}"
            for workflow in plan.workflows
        ]
        if body_lines:
            body_lines.append("")

        for workflow in plan.workflows:
            body_lines.extend(
                [
                    f"registration_{workflow.slot} = registrations.get_by_slot({workflow.slot})",
                    f"_dep_{workflow.slot}_type = registration_{workflow.slot}.provides",
                    (
                        f"_provider_{workflow.slot} = "
                        f"registration_{workflow.slot}.{workflow.provider_attribute}"
                    ),
                    "",
                ],
            )

        body_lines.append("return RootResolver(cleanup_enabled)")
        return self._build_function_template.render(
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _stored_non_root_scopes(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_scope_level: int,
    ) -> tuple[ScopePlan, ...]:
        return tuple(
            scope
            for scope in plan.scopes
            if not scope.is_root and scope.scope_level <= class_scope_level
        )

    def _ancestor_non_root_scopes(
        self,
        *,
        plan: ResolverGenerationPlan,
        scope_level: int,
    ) -> tuple[ScopePlan, ...]:
        return tuple(
            scope for scope in plan.scopes if not scope.is_root and scope.scope_level < scope_level
        )

    def _uses_stateless_scope_reuse(self, *, plan: ResolverGenerationPlan) -> bool:
        return not any(workflow.scope_level > plan.root_scope_level for workflow in plan.workflows)

    def _template(self, text: str) -> Template:
        return self._env.from_string(text)

    def _indent_block(self, block: str) -> str:
        return indent(block, _INDENT)

    def _indent_lines(self, lines: list[str], depth: int) -> list[str]:
        prefix = _INDENT * depth
        return [f"{prefix}{line}" if line else "" for line in lines]

    def _join_lines(self, lines: list[str]) -> str:
        return "\n".join(lines)


def main() -> None:
    renderer = ResolversTemplateRenderer()
    rendered_code = renderer.get_providers_code(
        root_scope=Scope.APP,
        registrations=ProvidersRegistrations(),
    )
    print(rendered_code)  # noqa: T201


if __name__ == "__main__":
    main()
