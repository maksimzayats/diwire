from __future__ import annotations

import inspect
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from textwrap import indent

from diwire.injection import INJECT_RESOLVER_KWARG
from diwire.providers import ProviderDependency, ProvidersRegistrations
from diwire.resolvers.templates.mini_jinja import Environment, Template
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
_MIN_CONSTRUCTOR_BASE_ARGUMENTS = 2
_MAX_INLINE_ROOT_DEPENDENCY_DEPTH = 3
_GENERATOR_SOURCE = (
    "diwire.resolvers.templates.renderer.ResolversTemplateRenderer.get_providers_code"
)


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Context for rendering resolver templates."""

    root_scope: BaseScope
    scopes: type[BaseScopes]
    registrations: ProvidersRegistrations


@dataclass(frozen=True, slots=True)
class DependencyExpressionContext:
    """Context for generating dependency expressions in provider call arguments."""

    class_scope_level: int
    root_scope: ScopePlan
    workflow_by_slot: dict[int, ProviderWorkflowPlan]
    root_resolver_expression: str | None = None

    @property
    def root_resolver_expr(self) -> str:
        """Return expression that resolves the root resolver for current method context."""
        if self.root_resolver_expression is not None:
            return self.root_resolver_expression
        return f"self.{self.root_scope.resolver_attr_name}"


class ResolversTemplateRenderer:
    """Renderer for generated resolver code."""

    def __init__(self) -> None:
        self._env = Environment(autoescape=False)
        self._module_template = self._template(MODULE_TEMPLATE)
        self._imports_template = self._template(IMPORTS_TEMPLATE)
        self._globals_template = self._template(GLOBALS_TEMPLATE)
        self._class_template = self._template(CLASS_TEMPLATE)
        self._init_method_template = self._template(INIT_METHOD_TEMPLATE)
        self._enter_scope_method_template = self._template(ENTER_SCOPE_METHOD_TEMPLATE)
        self._context_enter_method_template = self._template(CONTEXT_ENTER_METHOD_TEMPLATE)
        self._context_aenter_method_template = self._template(CONTEXT_AENTER_METHOD_TEMPLATE)
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

        module_docstring_block = self._render_module_docstring(plan=plan)
        imports_block = self._render_imports(plan=plan)
        globals_block = self._render_globals(plan=plan)
        classes_block = self._render_classes(plan=plan)
        build_block = self._render_build_function(plan=plan)

        return self._module_template.render(
            module_docstring_block=module_docstring_block,
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

    def _render_module_docstring(self, *, plan: ResolverGenerationPlan) -> str:
        scope_summary = ", ".join(
            f"{scope.scope_name}:{scope.scope_level}" for scope in plan.scopes
        )
        slots = ", ".join(str(workflow.slot) for workflow in plan.workflows) or "none"
        lines = [
            "Generated DI resolver module.",
            "",
            f"Generated by: {_GENERATOR_SOURCE}",
            f"diwire version used for generation: {self._resolve_diwire_version()}",
            "",
            "Generation configuration:",
            f"- root scope level: {plan.root_scope_level}",
            f"- managed scopes: {scope_summary}",
            f"- lock mode: {plan.lock_mode.value}",
            f"- cleanup support enabled in graph: {plan.has_cleanup}",
            f"- provider count: {len(plan.workflows)}",
            f"- provider slots: {slots}",
            "",
            "Examples:",
            ">>> root = build_root_resolver(registrations)",
            ">>> service = root.resolve(SomeService)",
            ">>> async_service = await root.aresolve(SomeAsyncService)",
            ">>> request_scope = root.enter_scope()",
            ">>> scoped_service = request_scope.resolve(RequestScopedService)",
        ]
        return self._docstring_block(lines=lines, depth=0)

    def _render_globals(self, *, plan: ResolverGenerationPlan) -> str:
        scope_lines = [
            f"_scope_obj_{scope.scope_level}: Any = {scope.scope_level}" for scope in plan.scopes
        ]
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
            provider_globals_block="\n".join([*scope_lines, *provider_lines]),
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
        class_docstring_block = self._indent_block(
            self._docstring_block(
                lines=self._class_docstring_lines(plan=plan, class_plan=class_plan),
                depth=0,
            ),
        )
        slots_block = self._indent_block(
            self._render_slots_block(plan=plan, class_plan=class_plan),
        )
        init_method_block = self._indent_block(
            self._render_init_method(plan=plan, class_plan=class_plan),
        )
        enter_scope_method_block = self._indent_block(
            self._render_enter_scope_method(plan=plan, class_plan=class_plan),
        )
        resolve_method_block = self._indent_block(
            self._render_dispatch_resolve_method(plan=plan, class_plan=class_plan),
        )
        aresolve_method_block = self._indent_block(
            self._render_dispatch_aresolve_method(plan=plan, class_plan=class_plan),
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
        enter_method_block = self._context_enter_method_template.render(
            return_annotation=class_plan.class_name,
        ).strip()
        aenter_method_block = self._context_aenter_method_template.render(
            return_annotation=class_plan.class_name,
        ).strip()
        return self._class_template.render(
            class_name=class_plan.class_name,
            class_docstring_block=class_docstring_block,
            slots_block=slots_block,
            init_method_block=init_method_block,
            enter_scope_method_block=enter_scope_method_block,
            resolve_method_block=resolve_method_block,
            aresolve_method_block=aresolve_method_block,
            enter_method_block=self._indent_block(enter_method_block),
            exit_method_block=exit_method_block,
            aenter_method_block=self._indent_block(aenter_method_block),
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
            docstring_block=self._join_lines(
                self._indent_lines(
                    self._docstring_lines(
                        self._init_docstring_lines(
                            plan=plan,
                        ),
                    ),
                    1,
                ),
            ),
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _build_init_signature_lines(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
    ) -> list[str]:
        if class_plan.is_root:
            return ["cleanup_enabled: bool = True,"] if plan.has_cleanup else []

        if self._uses_stateless_scope_reuse(plan=plan):
            signature_lines = ["root_resolver: RootResolver,"]
            if plan.has_cleanup:
                signature_lines.append("cleanup_enabled: bool = True,")
            return signature_lines

        ancestor_lines = [
            f"{scope.resolver_arg_name}: Any = _MISSING_RESOLVER,"
            for scope in self._ancestor_non_root_scopes(
                plan=plan,
                scope_level=class_plan.scope_level,
            )
        ]
        signature_lines = ["root_resolver: RootResolver,"]
        if plan.has_cleanup:
            signature_lines.append("cleanup_enabled: bool = True,")
        signature_lines.extend(ancestor_lines)
        return signature_lines

    def _render_slots_block(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
    ) -> str:
        slots = self._class_slots(plan=plan, class_plan=class_plan)
        lines = ["__slots__ = ("]
        lines.extend(f'    "{slot}",' for slot in slots)
        lines.append(")")
        return self._join_lines(lines)

    def _class_slots(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
    ) -> tuple[str, ...]:
        slots: list[str] = ["_root_resolver"]
        if plan.has_cleanup:
            slots.append("_cleanup_enabled")
        if class_plan.is_root:
            slots.append("__dict__")
        if plan.has_cleanup:
            slots.append("_cleanup_callbacks")

        slots.append(plan.scopes[0].resolver_attr_name)

        uses_stateless_scope_reuse = self._uses_stateless_scope_reuse(plan=plan)
        if not uses_stateless_scope_reuse:
            slots.extend(
                scope.resolver_attr_name
                for scope in self._stored_non_root_scopes(
                    plan=plan,
                    class_scope_level=class_plan.scope_level,
                )
            )

        if uses_stateless_scope_reuse and class_plan.is_root:
            slots.extend(
                f"_scope_resolver_{scope.scope_level}" for scope in plan.scopes if not scope.is_root
            )

        slots.extend(
            f"_cache_{workflow.slot}"
            for workflow in plan.workflows
            if workflow.is_cached and workflow.cache_owner_scope_level == class_plan.scope_level
        )
        return tuple(self._unique_ordered(slots))

    def _build_init_body_lines(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
    ) -> list[str]:
        body_lines = self._base_init_body_lines(plan=plan, class_plan=class_plan)

        uses_stateless_scope_reuse = self._uses_stateless_scope_reuse(plan=plan)
        if not uses_stateless_scope_reuse:
            for scope in self._stored_non_root_scopes(
                plan=plan,
                class_scope_level=class_plan.scope_level,
            ):
                body_lines.append(
                    f"self.{scope.resolver_attr_name} = {scope.resolver_arg_name}",
                )

        if uses_stateless_scope_reuse and class_plan.is_root:
            body_lines.extend(self._stateless_scope_reuse_init_lines(plan=plan))

        body_lines.extend(
            f"self._cache_{workflow.slot} = _MISSING_CACHE"
            for workflow in plan.workflows
            if workflow.is_cached and workflow.cache_owner_scope_level == class_plan.scope_level
        )
        return body_lines

    def _base_init_body_lines(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
    ) -> list[str]:
        body_lines: list[str] = []
        if plan.has_cleanup:
            body_lines.append("self._cleanup_enabled = cleanup_enabled")
        body_lines.append(
            "self._root_resolver = self"
            if class_plan.is_root
            else "self._root_resolver = root_resolver",
        )
        if plan.has_cleanup:
            body_lines.append("self._cleanup_callbacks: list[tuple[int, Any]] = []")
        return body_lines

    def _stateless_scope_reuse_init_lines(self, *, plan: ResolverGenerationPlan) -> list[str]:
        constructor_arguments = ["self._root_resolver"]
        if plan.has_cleanup:
            constructor_arguments.append("self._cleanup_enabled")
        joined_arguments = ", ".join(constructor_arguments)

        return [
            f"self._scope_resolver_{scope.scope_level} = {scope.class_name}({joined_arguments})"
            for scope in plan.scopes
            if not scope.is_root
        ]

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
        return_annotation = self._enter_scope_return_annotation(
            class_plan=class_plan,
            explicit_candidates=explicit_candidates,
        )
        docstring_block = self._join_lines(
            self._indent_lines(
                self._docstring_lines(
                    self._enter_scope_docstring_lines(
                        class_plan=class_plan,
                        explicit_candidates=explicit_candidates,
                    ),
                ),
                1,
            ),
        )
        if immediate_next is None:
            return self._enter_scope_method_template.render(
                return_annotation=return_annotation,
                docstring_block=docstring_block,
                body_block=self._join_lines(
                    self._indent_lines(
                        [
                            f'msg = "Cannot enter deeper scope from level {class_plan.scope_level}."',
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
            (
                f"if scope is _scope_obj_{default_next.scope_level} "
                f"or scope == {default_next.scope_level}:"
            ),
            *self._indent_lines(
                self._constructor_return_lines(
                    plan=plan,
                    current_scope_level=class_plan.scope_level,
                    target_scope=default_next,
                ),
                1,
            ),
            "if scope is None:",
            *self._indent_lines(
                self._constructor_return_lines(
                    plan=plan,
                    current_scope_level=class_plan.scope_level,
                    target_scope=default_next,
                ),
                1,
            ),
            "target_scope_level = scope",
        ]

        body_lines.extend(
            [
                (
                    f"if target_scope_level is _scope_obj_{class_plan.scope_level} "
                    f"or target_scope_level == {class_plan.scope_level}:"
                ),
                "    return self",
                f"if target_scope_level <= {class_plan.scope_level}:",
                (
                    f'    msg = f"Cannot enter scope level {{target_scope_level}} from level '
                    f'{class_plan.scope_level}."'
                ),
                "    raise DIWireScopeMismatchError(msg)",
            ],
        )

        for candidate in explicit_candidates:
            if candidate.scope_level == default_next.scope_level:
                continue
            body_lines.append(
                (
                    f"if target_scope_level is _scope_obj_{candidate.scope_level} "
                    f"or target_scope_level == {candidate.scope_level}:"
                ),
            )
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
                    f'msg = f"Scope level {{target_scope_level}} is not a valid next transition '
                    f'from level {class_plan.scope_level}."'
                ),
                "raise DIWireScopeMismatchError(msg)",
            ],
        )
        return self._enter_scope_method_template.render(
            return_annotation=return_annotation,
            docstring_block=docstring_block,
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _enter_scope_return_annotation(
        self,
        *,
        class_plan: ScopePlan,
        explicit_candidates: tuple[ScopePlan, ...],
    ) -> str:
        if not explicit_candidates:
            return "NoReturn"
        possible_returns = [class_plan.class_name]
        possible_returns.extend(scope.class_name for scope in explicit_candidates)
        unique_returns = self._unique_ordered(possible_returns)
        return " | ".join(unique_returns)

    def _constructor_return_lines(
        self,
        *,
        plan: ResolverGenerationPlan,
        current_scope_level: int,
        target_scope: ScopePlan,
    ) -> list[str]:
        if self._uses_stateless_scope_reuse(plan=plan):
            return [f"return self._root_resolver._scope_resolver_{target_scope.scope_level}"]

        arguments = [
            "self" if current_scope_level == plan.root_scope_level else "self._root_resolver",
        ]
        if plan.has_cleanup:
            arguments.append("self._cleanup_enabled")

        constructor_base_arguments = (
            _MIN_CONSTRUCTOR_BASE_ARGUMENTS
            if plan.has_cleanup
            else _MIN_CONSTRUCTOR_BASE_ARGUMENTS - 1
        )
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
        while len(arguments) > constructor_base_arguments and arguments[-1] == "_MISSING_RESOLVER":
            arguments.pop()

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

    def _render_dispatch_resolve_method(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
    ) -> str:
        ordered_workflows = self._dispatch_workflows(plan=plan, class_plan=class_plan)
        body_lines: list[str] = ["# Fast path identity checks to avoid reflective dispatch."]
        for workflow in ordered_workflows:
            call_expression = self._dispatch_sync_call_expression(
                plan=plan,
                class_plan=class_plan,
                workflow=workflow,
            )
            body_lines.extend(
                [
                    f"if dependency is _dep_{workflow.slot}_type:",
                    f"    return {call_expression}",
                ],
            )
        body_lines.extend(
            [
                "# Any dependency not pre-bound in build_root_resolver is unknown here.",
                'msg = f"Dependency {dependency!r} is not registered."',
                "raise DIWireDependencyNotRegisteredError(msg)",
            ],
        )
        return self._resolve_dispatch_template.render(
            docstring_block=self._join_lines(
                self._indent_lines(
                    self._docstring_lines(
                        self._dispatch_docstring_lines(plan=plan, is_async=False),
                    ),
                    1,
                ),
            ),
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _render_dispatch_aresolve_method(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
    ) -> str:
        ordered_workflows = self._dispatch_workflows(plan=plan, class_plan=class_plan)
        body_lines: list[str] = ["# Fast path identity checks for asynchronous resolution."]
        for workflow in ordered_workflows:
            call_expression = self._dispatch_async_call_expression(
                plan=plan,
                class_plan=class_plan,
                workflow=workflow,
            )
            body_lines.extend(
                [
                    f"if dependency is _dep_{workflow.slot}_type:",
                    f"    return await {call_expression}",
                ],
            )
        body_lines.extend(
            [
                "# Any dependency not pre-bound in build_root_resolver is unknown here.",
                'msg = f"Dependency {dependency!r} is not registered."',
                "raise DIWireDependencyNotRegisteredError(msg)",
            ],
        )
        return self._aresolve_dispatch_template.render(
            docstring_block=self._join_lines(
                self._indent_lines(
                    self._docstring_lines(self._dispatch_docstring_lines(plan=plan, is_async=True)),
                    1,
                ),
            ),
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _dispatch_sync_call_expression(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
        workflow: ProviderWorkflowPlan,
    ) -> str:
        if (
            class_plan.is_root
            and workflow.is_cached
            and workflow.cache_owner_scope_level == plan.root_scope_level
        ):
            return f"self.resolve_{workflow.slot}()"
        return f"{class_plan.class_name}.resolve_{workflow.slot}(self)"

    def _dispatch_async_call_expression(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
        workflow: ProviderWorkflowPlan,
    ) -> str:
        if (
            class_plan.is_root
            and workflow.is_cached
            and workflow.cache_owner_scope_level == plan.root_scope_level
        ):
            return f"self.aresolve_{workflow.slot}()"
        return f"{class_plan.class_name}.aresolve_{workflow.slot}(self)"

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
                behavior_note = (
                    "This resolver cannot access the provider yet because the required scope "
                    "is deeper than the current resolver scope."
                )
            else:
                owner_scope = scope_by_level[owner_scope_level]
                if owner_scope.is_root:
                    body_lines = [
                        f"return self.{owner_scope.resolver_attr_name}.resolve_{workflow.slot}()",
                    ]
                else:
                    body_lines = self._render_owner_guard(
                        workflow=workflow,
                        scope_attr_name=owner_scope.resolver_attr_name,
                        resolver_name="owner_resolver",
                    )
                    body_lines.append(f"return owner_resolver.resolve_{workflow.slot}()")
                behavior_note = (
                    "This resolver delegates to the cache owner resolver so scoped caching remains "
                    "consistent across nested resolvers."
                )
            return self._sync_method_template.render(
                slot=workflow.slot,
                docstring_block=self._resolver_docstring_block(
                    class_plan=class_plan,
                    workflow=workflow,
                    behavior_note=behavior_note,
                    is_async_method=False,
                ),
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        body_lines = self._render_provider_scope_guard(
            class_scope_level=class_plan.scope_level,
            scope_by_level=scope_by_level,
            workflow=workflow,
        )
        if (
            workflow.scope_level < class_plan.scope_level
            and workflow.max_required_scope_level <= workflow.scope_level
        ):
            owner_scope = scope_by_level[workflow.scope_level]
            if owner_scope.is_root:
                body_lines = [
                    f"return self.{owner_scope.resolver_attr_name}.resolve_{workflow.slot}()",
                ]
            else:
                body_lines = self._render_owner_guard(
                    workflow=workflow,
                    scope_attr_name=owner_scope.resolver_attr_name,
                    resolver_name="owner_resolver",
                )
                body_lines.append(f"return owner_resolver.resolve_{workflow.slot}()")
            return self._sync_method_template.render(
                slot=workflow.slot,
                docstring_block=self._resolver_docstring_block(
                    class_plan=class_plan,
                    workflow=workflow,
                    behavior_note=(
                        "This resolver delegates to the provider declaration scope because the "
                        "dependency graph does not require deeper scope access."
                    ),
                    is_async_method=False,
                ),
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        behavior_note = (
            "Builds the provider value in this resolver, enforcing scope guards and cache policy."
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
                docstring_block=self._resolver_docstring_block(
                    class_plan=class_plan,
                    workflow=workflow,
                    behavior_note=(
                        "Synchronous access is blocked because the provider graph requires async "
                        "resolution."
                    ),
                    is_async_method=False,
                ),
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        uses_thread_lock = (
            workflow.is_cached and workflow.concurrency_safe and plan.lock_mode is LockMode.THREAD
        )
        if uses_thread_lock:
            body_lines.extend(
                [
                    f"cached_value = self._cache_{workflow.slot}",
                    "if cached_value is not _MISSING_CACHE:",
                    "    return cached_value",
                ],
            )
            body_lines.append(f"with _dep_{workflow.slot}_thread_lock:")
            body_lines.extend(
                self._indent_lines(
                    [
                        f"if (cached_value := self._cache_{workflow.slot}) is not _MISSING_CACHE:",
                        "    return cached_value",
                        *self._render_local_value_build(
                            workflow=workflow,
                            is_async_call=False,
                            class_plan=class_plan,
                            scope_by_level=scope_by_level,
                            workflow_by_slot={item.slot: item for item in plan.workflows},
                        ),
                        *self._render_sync_cache_replace(plan=plan, workflow=workflow),
                        "return value",
                    ],
                    1,
                ),
            )
            return self._sync_method_template.render(
                slot=workflow.slot,
                docstring_block=self._resolver_docstring_block(
                    class_plan=class_plan,
                    workflow=workflow,
                    behavior_note=behavior_note,
                    is_async_method=False,
                ),
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        if workflow.is_cached:
            build_and_cache_lines = [
                *self._render_local_value_build(
                    workflow=workflow,
                    is_async_call=False,
                    class_plan=class_plan,
                    scope_by_level=scope_by_level,
                    workflow_by_slot={item.slot: item for item in plan.workflows},
                ),
                *self._render_sync_cache_replace(plan=plan, workflow=workflow),
                "return value",
            ]
            body_lines.extend(
                [
                    f"cached_value = self._cache_{workflow.slot}",
                    "if cached_value is _MISSING_CACHE:",
                    *self._indent_lines(build_and_cache_lines, 1),
                    "return cached_value",
                ],
            )
            return self._sync_method_template.render(
                slot=workflow.slot,
                docstring_block=self._resolver_docstring_block(
                    class_plan=class_plan,
                    workflow=workflow,
                    behavior_note=behavior_note,
                    is_async_method=False,
                ),
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        body_lines.extend(
            [
                *self._render_local_value_build(
                    workflow=workflow,
                    is_async_call=False,
                    class_plan=class_plan,
                    scope_by_level=scope_by_level,
                    workflow_by_slot={item.slot: item for item in plan.workflows},
                ),
                *self._render_sync_cache_replace(plan=plan, workflow=workflow),
                "return value",
            ],
        )
        return self._sync_method_template.render(
            slot=workflow.slot,
            docstring_block=self._resolver_docstring_block(
                class_plan=class_plan,
                workflow=workflow,
                behavior_note=behavior_note,
                is_async_method=False,
            ),
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
                docstring_block=self._resolver_docstring_block(
                    class_plan=class_plan,
                    workflow=workflow,
                    behavior_note=(
                        "Async variant delegates to sync resolution because this provider graph "
                        "does not require awaitable operations."
                    ),
                    is_async_method=True,
                ),
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
                behavior_note = (
                    "This resolver cannot access the provider yet because the required scope "
                    "is deeper than the current resolver scope."
                )
            else:
                owner_scope = scope_by_level[owner_scope_level]
                if owner_scope.is_root:
                    body_lines = [
                        f"return await self.{owner_scope.resolver_attr_name}.aresolve_{workflow.slot}()",
                    ]
                else:
                    body_lines = self._render_owner_guard(
                        workflow=workflow,
                        scope_attr_name=owner_scope.resolver_attr_name,
                        resolver_name="owner_resolver",
                    )
                    body_lines.append(f"return await owner_resolver.aresolve_{workflow.slot}()")
                behavior_note = (
                    "This resolver delegates to the cache owner resolver so scoped caching remains "
                    "consistent across nested resolvers."
                )
            return self._async_method_template.render(
                slot=workflow.slot,
                docstring_block=self._resolver_docstring_block(
                    class_plan=class_plan,
                    workflow=workflow,
                    behavior_note=behavior_note,
                    is_async_method=True,
                ),
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        body_lines = self._render_provider_scope_guard(
            class_scope_level=class_plan.scope_level,
            scope_by_level=scope_by_level,
            workflow=workflow,
        )
        if (
            workflow.scope_level < class_plan.scope_level
            and workflow.max_required_scope_level <= workflow.scope_level
        ):
            owner_scope = scope_by_level[workflow.scope_level]
            if owner_scope.is_root:
                body_lines = [
                    f"return await self.{owner_scope.resolver_attr_name}.aresolve_{workflow.slot}()",
                ]
            else:
                body_lines = self._render_owner_guard(
                    workflow=workflow,
                    scope_attr_name=owner_scope.resolver_attr_name,
                    resolver_name="owner_resolver",
                )
                body_lines.append(f"return await owner_resolver.aresolve_{workflow.slot}()")
            return self._async_method_template.render(
                slot=workflow.slot,
                docstring_block=self._resolver_docstring_block(
                    class_plan=class_plan,
                    workflow=workflow,
                    behavior_note=(
                        "This resolver delegates to the provider declaration scope because the "
                        "dependency graph does not require deeper scope access."
                    ),
                    is_async_method=True,
                ),
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        behavior_note = (
            "Builds the provider value in this resolver, enforcing scope guards and cache policy."
        )
        uses_async_lock = (
            workflow.is_cached and workflow.concurrency_safe and plan.lock_mode is LockMode.ASYNC
        )
        if uses_async_lock:
            body_lines.extend(
                [
                    f"cached_value = self._cache_{workflow.slot}",
                    "if cached_value is not _MISSING_CACHE:",
                    "    return cached_value",
                ],
            )
            body_lines.append(f"async with _dep_{workflow.slot}_async_lock:")
            body_lines.extend(
                self._indent_lines(
                    [
                        f"if (cached_value := self._cache_{workflow.slot}) is not _MISSING_CACHE:",
                        "    return cached_value",
                        *self._render_local_value_build(
                            workflow=workflow,
                            is_async_call=True,
                            class_plan=class_plan,
                            scope_by_level=scope_by_level,
                            workflow_by_slot={item.slot: item for item in plan.workflows},
                        ),
                        *self._render_async_cache_replace(plan=plan, workflow=workflow),
                        "return value",
                    ],
                    1,
                ),
            )
            return self._async_method_template.render(
                slot=workflow.slot,
                docstring_block=self._resolver_docstring_block(
                    class_plan=class_plan,
                    workflow=workflow,
                    behavior_note=behavior_note,
                    is_async_method=True,
                ),
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        if workflow.is_cached:
            build_and_cache_lines = [
                *self._render_local_value_build(
                    workflow=workflow,
                    is_async_call=True,
                    class_plan=class_plan,
                    scope_by_level=scope_by_level,
                    workflow_by_slot={item.slot: item for item in plan.workflows},
                ),
                *self._render_async_cache_replace(plan=plan, workflow=workflow),
                "return value",
            ]
            body_lines.extend(
                [
                    f"cached_value = self._cache_{workflow.slot}",
                    "if cached_value is _MISSING_CACHE:",
                    *self._indent_lines(build_and_cache_lines, 1),
                    "return cached_value",
                ],
            )
            return self._async_method_template.render(
                slot=workflow.slot,
                docstring_block=self._resolver_docstring_block(
                    class_plan=class_plan,
                    workflow=workflow,
                    behavior_note=behavior_note,
                    is_async_method=True,
                ),
                body_block=self._join_lines(self._indent_lines(body_lines, 1)),
            ).strip()

        body_lines.extend(
            [
                *self._render_local_value_build(
                    workflow=workflow,
                    is_async_call=True,
                    class_plan=class_plan,
                    scope_by_level=scope_by_level,
                    workflow_by_slot={item.slot: item for item in plan.workflows},
                ),
                *self._render_async_cache_replace(plan=plan, workflow=workflow),
                "return value",
            ],
        )
        return self._async_method_template.render(
            slot=workflow.slot,
            docstring_block=self._resolver_docstring_block(
                class_plan=class_plan,
                workflow=workflow,
                behavior_note=behavior_note,
                is_async_method=True,
            ),
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _render_provider_scope_guard(
        self,
        *,
        class_scope_level: int,
        scope_by_level: dict[int, ScopePlan],
        workflow: ProviderWorkflowPlan,
    ) -> list[str]:
        needs_scope_resolver = workflow.provider_attribute in {"generator", "context_manager"}

        if workflow.scope_level > class_scope_level:
            return self._scope_mismatch_lines(workflow=workflow)

        if workflow.scope_level == class_scope_level:
            return ["provider_scope_resolver = self"] if needs_scope_resolver else []

        scope = scope_by_level[workflow.scope_level]
        scope_reference = f"self.{scope.resolver_attr_name}"
        if scope.is_root:
            return [f"provider_scope_resolver = {scope_reference}"] if needs_scope_resolver else []

        if needs_scope_resolver:
            return [
                f"provider_scope_resolver = {scope_reference}",
                "if provider_scope_resolver is _MISSING_RESOLVER:",
                *self._indent_lines(self._scope_mismatch_lines(workflow=workflow), 1),
            ]

        return [
            f"if {scope_reference} is _MISSING_RESOLVER:",
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
        class_plan: ScopePlan,
        scope_by_level: dict[int, ScopePlan],
        workflow_by_slot: dict[int, ProviderWorkflowPlan],
    ) -> list[str]:
        arguments = self._build_call_arguments(
            workflow=workflow,
            is_async_call=is_async_call,
            class_plan=class_plan,
            scope_by_level=scope_by_level,
            workflow_by_slot=workflow_by_slot,
        )
        root_resolver_alias_lines = self._root_resolver_alias_lines(arguments=arguments)
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
            return [*root_resolver_alias_lines, *lines]

        if workflow.provider_attribute == "generator":
            lines = self._render_generator_build(
                workflow=workflow,
                arguments=arguments,
                is_async_call=is_async_call,
            )
            return [*root_resolver_alias_lines, *lines]

        if workflow.provider_attribute == "context_manager":
            lines = self._render_context_manager_build(
                workflow=workflow,
                arguments=arguments,
            )
            return [*root_resolver_alias_lines, *lines]

        msg = f"Unsupported provider attribute {workflow.provider_attribute!r}."
        raise ValueError(msg)

    def _root_resolver_alias_lines(self, *, arguments: tuple[str, ...]) -> list[str]:
        if not any("_root_resolver" in argument for argument in arguments):
            return []
        return ["_root_resolver = self._root_resolver"]

    def _build_call_arguments(
        self,
        *,
        workflow: ProviderWorkflowPlan,
        is_async_call: bool,
        class_plan: ScopePlan,
        scope_by_level: dict[int, ScopePlan],
        workflow_by_slot: dict[int, ProviderWorkflowPlan],
    ) -> tuple[str, ...]:
        arguments: list[str] = []
        root_scope_level = min(scope_by_level)
        root_scope = scope_by_level[root_scope_level]
        expression_context = DependencyExpressionContext(
            class_scope_level=class_plan.scope_level,
            root_scope=root_scope,
            root_resolver_expression=(
                "self" if class_plan.scope_level == root_scope_level else "_root_resolver"
            ),
            workflow_by_slot=workflow_by_slot,
        )

        for dependency, dependency_slot, dependency_requires_async in zip(
            workflow.dependencies,
            workflow.dependency_slots,
            workflow.dependency_requires_async,
            strict=True,
        ):
            dependency_workflow = workflow_by_slot[dependency_slot]
            expression = self._inline_root_sync_dependency_expression(
                dependency_workflow=dependency_workflow,
                dependency_requires_async=dependency_requires_async,
                context=expression_context,
                depth=0,
            )
            if expression is None:
                expression = self._dependency_expression_for_class(
                    dependency_workflow=dependency_workflow,
                    dependency_requires_async=dependency_requires_async,
                    is_async_call=is_async_call,
                    context=expression_context,
                )
            arguments.append(
                self._format_dependency_argument(
                    dependency=dependency,
                    expression=expression,
                    prefer_positional=workflow.dependency_order_is_signature_order,
                ),
            )

        if workflow.provider_is_inject_wrapper:
            self._append_internal_resolver_argument(
                arguments=arguments,
                resolver_expression="self",
            )

        return tuple(arguments)

    def _dependency_expression_for_class(
        self,
        *,
        dependency_workflow: ProviderWorkflowPlan,
        dependency_requires_async: bool,
        is_async_call: bool,
        context: DependencyExpressionContext,
    ) -> str:
        class_scope_level = context.class_scope_level
        root_scope = context.root_scope
        dependency_slot = dependency_workflow.slot
        if is_async_call and dependency_requires_async:
            return f"await self.aresolve_{dependency_slot}()"

        if is_async_call:
            return f"self.resolve_{dependency_slot}()"

        if (
            dependency_workflow.is_cached
            and dependency_workflow.cache_owner_scope_level == class_scope_level
        ):
            return (
                f"self._cache_{dependency_slot} if self._cache_{dependency_slot} is not "
                f"_MISSING_CACHE else self.resolve_{dependency_slot}()"
            )

        if (
            dependency_workflow.scope_level < class_scope_level
            and dependency_workflow.max_required_scope_level <= dependency_workflow.scope_level
            and dependency_workflow.scope_level == root_scope.scope_level
        ):
            return f"{context.root_resolver_expr}.resolve_{dependency_slot}()"

        return f"self.resolve_{dependency_slot}()"

    def _inline_root_sync_dependency_expression(
        self,
        *,
        dependency_workflow: ProviderWorkflowPlan,
        dependency_requires_async: bool,
        context: DependencyExpressionContext,
        depth: int,
    ) -> str | None:
        if not self._can_inline_root_sync_dependency(
            dependency_workflow=dependency_workflow,
            dependency_requires_async=dependency_requires_async,
            context=context,
            depth=depth,
        ):
            return None

        dependency_slot = dependency_workflow.slot
        root_resolver_expression = context.root_resolver_expr
        if dependency_workflow.is_cached:
            return self._inline_root_cached_expression(
                dependency_slot=dependency_slot,
                root_resolver_expression=root_resolver_expression,
            )

        if dependency_workflow.provider_attribute not in {"concrete_type", "factory"}:
            return None

        arguments = self._inline_root_dependency_arguments(
            dependency_workflow=dependency_workflow,
            context=context,
            depth=depth,
        )
        if arguments is None:
            return None
        rendered_arguments = list(arguments)
        if dependency_workflow.provider_is_inject_wrapper:
            self._append_internal_resolver_argument(
                arguments=rendered_arguments,
                resolver_expression=root_resolver_expression,
            )

        return self._render_callable_expression(
            callable_expression=f"_provider_{dependency_slot}",
            arguments=tuple(rendered_arguments),
        )

    def _can_inline_root_sync_dependency(
        self,
        *,
        dependency_workflow: ProviderWorkflowPlan,
        dependency_requires_async: bool,
        context: DependencyExpressionContext,
        depth: int,
    ) -> bool:
        root_scope_level = context.root_scope.scope_level
        return (
            not dependency_requires_async
            and depth <= _MAX_INLINE_ROOT_DEPENDENCY_DEPTH
            and context.class_scope_level > root_scope_level
            and dependency_workflow.scope_level == root_scope_level
            and dependency_workflow.max_required_scope_level <= root_scope_level
            and not dependency_workflow.is_provider_async
            and not dependency_workflow.needs_cleanup
        )

    def _inline_root_cached_expression(
        self,
        *,
        dependency_slot: int,
        root_resolver_expression: str,
    ) -> str:
        return (
            f"{root_resolver_expression}._cache_{dependency_slot} if "
            f"{root_resolver_expression}._cache_{dependency_slot} is not _MISSING_CACHE else "
            f"{root_resolver_expression}.resolve_{dependency_slot}()"
        )

    def _inline_root_dependency_arguments(
        self,
        *,
        dependency_workflow: ProviderWorkflowPlan,
        context: DependencyExpressionContext,
        depth: int,
    ) -> tuple[str, ...] | None:
        arguments: list[str] = []
        for dependency, slot, requires_async in zip(
            dependency_workflow.dependencies,
            dependency_workflow.dependency_slots,
            dependency_workflow.dependency_requires_async,
            strict=True,
        ):
            nested_expression = self._inline_root_nested_dependency_expression(
                slot=slot,
                requires_async=requires_async,
                context=context,
                depth=depth,
            )
            if nested_expression is None:
                return None
            arguments.append(
                self._format_dependency_argument(
                    dependency=dependency,
                    expression=nested_expression,
                    prefer_positional=dependency_workflow.dependency_order_is_signature_order,
                ),
            )
        return tuple(arguments)

    def _inline_root_nested_dependency_expression(
        self,
        *,
        slot: int,
        requires_async: bool,
        context: DependencyExpressionContext,
        depth: int,
    ) -> str | None:
        root_scope_level = context.root_scope.scope_level
        root_resolver_expression = context.root_resolver_expr
        nested_workflow = context.workflow_by_slot[slot]
        nested_expression = self._inline_root_sync_dependency_expression(
            dependency_workflow=nested_workflow,
            dependency_requires_async=requires_async,
            context=context,
            depth=depth + 1,
        )
        if nested_expression is not None:
            return nested_expression

        if requires_async:
            return None
        if nested_workflow.scope_level != root_scope_level:
            return None
        if nested_workflow.max_required_scope_level > root_scope_level:
            return None
        return f"{root_resolver_expression}.resolve_{slot}()"

    def _format_dependency_argument(
        self,
        *,
        dependency: ProviderDependency,
        expression: str,
        prefer_positional: bool,
    ) -> str:
        kind = dependency.parameter.kind
        if kind is inspect.Parameter.POSITIONAL_ONLY:
            return expression
        if kind is inspect.Parameter.POSITIONAL_OR_KEYWORD and prefer_positional:
            return expression
        if kind is inspect.Parameter.VAR_POSITIONAL:
            return f"*{expression}"
        if kind is inspect.Parameter.VAR_KEYWORD:
            return f"**{expression}"
        return f"{dependency.parameter.name}={expression}"

    def _append_internal_resolver_argument(
        self,
        *,
        arguments: list[str],
        resolver_expression: str,
    ) -> None:
        resolver_argument = f"{INJECT_RESOLVER_KWARG}={resolver_expression}"
        var_keyword_index = next(
            (index for index, argument in enumerate(arguments) if argument.startswith("**")),
            None,
        )
        if var_keyword_index is None:
            arguments.append(resolver_argument)
            return
        arguments.insert(var_keyword_index, resolver_argument)

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

    def _render_sync_cache_replace(
        self,
        *,
        plan: ResolverGenerationPlan,
        workflow: ProviderWorkflowPlan,
    ) -> list[str]:
        if not workflow.is_cached:
            return []
        if workflow.cache_owner_scope_level != plan.root_scope_level:
            return [f"self._cache_{workflow.slot} = value"]
        return [
            f"self._cache_{workflow.slot} = value",
            f"self.resolve_{workflow.slot} = lambda: value  # type: ignore[method-assign]",
            "",
            "async def _cached() -> Any:",
            "    return value",
            "",
            f"self.aresolve_{workflow.slot} = _cached  # type: ignore[method-assign]",
        ]

    def _render_async_cache_replace(
        self,
        *,
        plan: ResolverGenerationPlan,
        workflow: ProviderWorkflowPlan,
    ) -> list[str]:
        if not workflow.is_cached:
            return []
        if workflow.cache_owner_scope_level != plan.root_scope_level:
            return [f"self._cache_{workflow.slot} = value"]
        return [
            f"self._cache_{workflow.slot} = value",
            "",
            "async def _cached() -> Any:",
            "    return value",
            "",
            f"self.aresolve_{workflow.slot} = _cached  # type: ignore[method-assign]",
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

    def _render_callable_expression(
        self,
        *,
        callable_expression: str,
        arguments: tuple[str, ...],
    ) -> str:
        if not arguments:
            return f"{callable_expression}()"
        joined_arguments = ", ".join(arguments)
        return f"{callable_expression}({joined_arguments})"

    def _render_build_function(self, *, plan: ResolverGenerationPlan) -> str:
        body_lines = [
            "# Bind module-level globals to this container registration snapshot.",
            "# This keeps hot paths in resolver methods free from dictionary lookups.",
        ]
        if plan.workflows:
            body_lines.extend(
                f"global _dep_{workflow.slot}_type, _provider_{workflow.slot}"
                for workflow in plan.workflows
            )
            body_lines.append("")
        else:
            body_lines.append("# No provider registrations are active for the selected root scope.")
            body_lines.append("")

        for workflow in plan.workflows:
            body_lines.extend(
                [
                    f"# --- Provider slot {workflow.slot} bootstrap metadata ---",
                    "# Read provider spec by stable slot id from registrations.",
                    f"registration_{workflow.slot} = registrations.get_by_slot({workflow.slot})",
                    "# Capture dependency identity token used by `resolve`/`aresolve` dispatch.",
                    f"_dep_{workflow.slot}_type = registration_{workflow.slot}.provides",
                    "# Capture provider object (instance/type/factory/generator/context manager).",
                    (
                        f"_provider_{workflow.slot} = "
                        f"registration_{workflow.slot}.{workflow.provider_attribute}"
                    ),
                    "",
                ],
            )

        body_lines.extend(
            [
                "# Construct a fresh root resolver configured with optional cleanup callbacks.",
                "return RootResolver(cleanup_enabled)"
                if plan.has_cleanup
                else "return RootResolver()",
            ],
        )
        return self._build_function_template.render(
            return_annotation="RootResolver",
            docstring_block=self._join_lines(
                self._indent_lines(
                    self._docstring_lines(self._build_function_docstring_lines(plan=plan)),
                    1,
                ),
            ),
            body_block=self._join_lines(self._indent_lines(body_lines, 1)),
        ).strip()

    def _class_docstring_lines(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_plan: ScopePlan,
    ) -> list[str]:
        managed_slots = ", ".join(str(workflow.slot) for workflow in plan.workflows) or "none"
        class_scope_slots = (
            ", ".join(
                str(workflow.slot)
                for workflow in plan.workflows
                if workflow.scope_level == class_plan.scope_level
            )
            or "none"
        )
        return [
            f"Generated resolver for scope '{class_plan.scope_name}' (level {class_plan.scope_level}).",
            "",
            "This class is generated and optimized for direct slot-based dependency resolution.",
            f"All visible provider slots: {managed_slots}.",
            f"Providers declared in this exact scope: {class_scope_slots}.",
        ]

    def _init_docstring_lines(
        self,
        *,
        plan: ResolverGenerationPlan,
    ) -> list[str]:
        reused_scopes = self._uses_stateless_scope_reuse(plan=plan)
        return [
            "Initialize resolver state for the current scope.",
            "",
            "The constructor wires scope ancestry references, cache slots, and optional cleanup state.",
            f"Root scope class: {plan.scopes[0].class_name}.",
            f"Stateless scope reuse enabled: {reused_scopes}.",
        ]

    def _enter_scope_docstring_lines(
        self,
        *,
        class_plan: ScopePlan,
        explicit_candidates: tuple[ScopePlan, ...],
    ) -> list[str]:
        transitions = (
            ", ".join(f"{scope.scope_name}:{scope.scope_level}" for scope in explicit_candidates)
            or "none"
        )
        return [
            "Open a deeper scope resolver from this resolver.",
            "",
            f"Current scope: {class_plan.scope_name}:{class_plan.scope_level}.",
            f"Allowed explicit transitions: {transitions}.",
            "Passing None follows the default transition for the scope graph.",
        ]

    def _dispatch_docstring_lines(
        self,
        *,
        plan: ResolverGenerationPlan,
        is_async: bool,
    ) -> list[str]:
        slots = ", ".join(str(workflow.slot) for workflow in plan.workflows) or "none"
        mode = "asynchronous" if is_async else "synchronous"
        return [
            f"Route a dependency token to a generated {mode} provider resolver method.",
            "",
            f"Known provider slots: {slots}.",
            "Dispatch uses identity checks against module-level `_dep_<slot>_type` globals.",
        ]

    def _resolver_docstring_block(
        self,
        *,
        class_plan: ScopePlan,
        workflow: ProviderWorkflowPlan,
        behavior_note: str,
        is_async_method: bool,
    ) -> str:
        return self._join_lines(
            self._indent_lines(
                self._docstring_lines(
                    self._resolver_docstring_lines(
                        class_plan=class_plan,
                        workflow=workflow,
                        behavior_note=behavior_note,
                        is_async_method=is_async_method,
                    ),
                ),
                1,
            ),
        )

    def _resolver_docstring_lines(
        self,
        *,
        class_plan: ScopePlan,
        workflow: ProviderWorkflowPlan,
        behavior_note: str,
        is_async_method: bool,
    ) -> list[str]:
        mode = "async" if is_async_method else "sync"
        cache_owner = self._cache_owner_scope_label(workflow=workflow)
        return [
            f"Provider slot {workflow.slot} resolver ({mode} method).",
            "",
            f"Returns: {self._format_symbol(workflow.provides)}",
            f"Provider spec kind: {workflow.provider_attribute}",
            f"Provider target: {self._format_provider_reference(workflow=workflow)}",
            f"Declared scope: {workflow.scope_name} (level {workflow.scope_level})",
            f"Declared lifetime: {self._format_lifetime(workflow=workflow)}",
            f"Cache policy: {'cached' if workflow.is_cached else 'transient'}",
            f"Cache owner scope: {cache_owner}",
            f"Concurrency-safe provider: {workflow.concurrency_safe}",
            f"Provider declared async: {workflow.is_provider_async}",
            f"Graph requires async: {workflow.requires_async}",
            f"Cleanup callbacks required: {workflow.needs_cleanup}",
            f"Resolver class handling this call: {class_plan.class_name}",
            f"Dependency wiring: {self._format_dependency_wiring(workflow=workflow)}",
            f"Behavior: {behavior_note}",
        ]

    def _build_function_docstring_lines(self, *, plan: ResolverGenerationPlan) -> list[str]:
        slots = ", ".join(str(workflow.slot) for workflow in plan.workflows) or "none"
        return [
            "Build and return the generated root resolver instance.",
            "",
            "This function rebinds module-level provider globals for the supplied registrations.",
            "Global rebinding makes `resolve_<slot>` methods run without registration lookups.",
            f"Provider slots configured during bootstrap: {slots}.",
            f"Root resolver class: {plan.scopes[0].class_name}.",
            "",
            "Examples:",
            ">>> root = build_root_resolver(registrations)",
            ">>> root.resolve(SomeService)",
            ">>> await root.aresolve(SomeAsyncService)",
            ">>> scoped = root.enter_scope()",
        ]

    def _format_provider_reference(self, *, workflow: ProviderWorkflowPlan) -> str:
        if workflow.provider_attribute == "instance":
            return f"instance of {self._format_symbol(type(workflow.provider_reference))}"
        return self._format_symbol(workflow.provider_reference)

    def _format_dependency_wiring(self, *, workflow: ProviderWorkflowPlan) -> str:
        if not workflow.dependencies:
            return "none"

        parts: list[str] = []
        for dependency, slot in zip(workflow.dependencies, workflow.dependency_slots, strict=True):
            kind_name = dependency.parameter.kind.name.lower()
            parts.append(
                (
                    f"{dependency.parameter.name} ({kind_name}) -> slot {slot} "
                    f"[{self._format_symbol(dependency.provides)}]"
                ),
            )
        return "; ".join(parts)

    def _format_lifetime(self, *, workflow: ProviderWorkflowPlan) -> str:
        if workflow.lifetime is None:
            return "none"
        return workflow.lifetime.name.lower()

    def _cache_owner_scope_label(self, *, workflow: ProviderWorkflowPlan) -> str:
        if workflow.cache_owner_scope_level is None:
            return "none"
        return str(workflow.cache_owner_scope_level)

    def _resolve_diwire_version(self) -> str:
        try:
            return version("diwire")
        except PackageNotFoundError:
            return "unknown"

    def _format_symbol(self, value: object) -> str:
        module_name = getattr(value, "__module__", None)
        qualname = getattr(value, "__qualname__", None)
        if isinstance(module_name, str) and isinstance(qualname, str):
            if module_name == "builtins":
                return qualname
            return f"{module_name}.{qualname}"

        text = str(value)
        if " at 0x" in text:
            value_type = type(value)
            type_module_name = getattr(value_type, "__module__", "builtins")
            type_qualname = getattr(value_type, "__qualname__", value_type.__name__)
            return f"{type_module_name}.{type_qualname}"
        return text

    def _docstring_lines(self, lines: list[str]) -> list[str]:
        return ['"""', *lines, '"""']

    def _docstring_block(self, *, lines: list[str], depth: int) -> str:
        return self._join_lines(self._indent_lines(self._docstring_lines(lines), depth))

    def _stored_non_root_scopes(
        self,
        *,
        plan: ResolverGenerationPlan,
        class_scope_level: int,
    ) -> tuple[ScopePlan, ...]:
        active_non_root_levels = self._active_non_root_scope_levels(plan=plan)
        return tuple(
            scope
            for scope in plan.scopes
            if (
                not scope.is_root
                and scope.scope_level < class_scope_level
                and scope.scope_level in active_non_root_levels
            )
        )

    def _ancestor_non_root_scopes(
        self,
        *,
        plan: ResolverGenerationPlan,
        scope_level: int,
    ) -> tuple[ScopePlan, ...]:
        active_non_root_levels = self._active_non_root_scope_levels(plan=plan)
        return tuple(
            scope
            for scope in plan.scopes
            if (
                not scope.is_root
                and scope.scope_level < scope_level
                and scope.scope_level in active_non_root_levels
            )
        )

    def _active_non_root_scope_levels(self, *, plan: ResolverGenerationPlan) -> set[int]:
        return {
            workflow.scope_level
            for workflow in plan.workflows
            if workflow.scope_level > plan.root_scope_level
        }

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

    def _unique_ordered(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        unique_values: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            unique_values.append(value)
        return unique_values

    def _dispatch_workflows(
        self,
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


def main() -> None:
    renderer = ResolversTemplateRenderer()
    rendered_code = renderer.get_providers_code(
        root_scope=Scope.APP,
        registrations=ProvidersRegistrations(),
    )
    print(rendered_code)  # noqa: T201


if __name__ == "__main__":
    main()
