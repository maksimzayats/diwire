from __future__ import annotations

import inspect

import pytest

from diwire import Container, Scope
from diwire._internal.providers import ProviderDependency
from diwire._internal.resolvers.templates import renderer as renderer_module
from diwire._internal.resolvers.templates.planner import (
    ProviderDependencyPlan,
    ProviderWorkflowPlan,
    ResolverGenerationPlan,
    ResolverGenerationPlanner,
)
from diwire._internal.resolvers.templates.renderer import (
    DependencyExpressionContext,
    ResolversTemplateRenderer,
)


def _plan_for_renderer() -> ResolverGenerationPlan:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(1, provides=int)
    return ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    ).build()


def _workflow_by_slot(plan: ResolverGenerationPlan) -> dict[int, ProviderWorkflowPlan]:
    return {workflow.slot: workflow for workflow in plan.workflows}


def test_provider_handle_dependency_expression_raises_when_inner_slot_is_missing() -> None:
    renderer = ResolversTemplateRenderer()
    plan = _plan_for_renderer()
    workflow = plan.workflows[0]
    parameter = inspect.Parameter(
        "dep",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    dependency = ProviderDependency(
        provides=int,
        parameter=parameter,
    )
    dependency_plan = ProviderDependencyPlan(
        kind="provider_handle",
        dependency=dependency,
        dependency_index=0,
        provider_inner_slot=None,
    )

    with pytest.raises(ValueError, match="missing provider inner slot"):
        renderer._provider_handle_dependency_expression(
            workflow=workflow,
            dependency_plan=dependency_plan,
        )


def test_context_dependency_expression_raises_when_global_key_name_is_missing() -> None:
    renderer = ResolversTemplateRenderer()
    plan = _plan_for_renderer()
    workflow = plan.workflows[0]
    parameter = inspect.Parameter(
        "dep",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    dependency = ProviderDependency(
        provides=int,
        parameter=parameter,
    )
    dependency_plan = ProviderDependencyPlan(
        kind="context",
        dependency=dependency,
        dependency_index=0,
        ctx_key_global_name=None,
    )

    with pytest.raises(ValueError, match="Missing context key binding global"):
        renderer._context_dependency_expression(
            workflow=workflow,
            dependency_plan=dependency_plan,
        )


def test_provider_dependency_expression_raises_when_dependency_slot_is_missing() -> None:
    renderer = ResolversTemplateRenderer()
    plan = _plan_for_renderer()
    workflow = plan.workflows[0]
    parameter = inspect.Parameter(
        "dep",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    dependency = ProviderDependency(
        provides=int,
        parameter=parameter,
    )
    dependency_plan = ProviderDependencyPlan(
        kind="provider",
        dependency=dependency,
        dependency_index=0,
        dependency_slot=None,
    )

    with pytest.raises(ValueError, match="is missing dependency slot"):
        context = DependencyExpressionContext(
            class_scope_level=plan.scopes[0].scope_level,
            root_scope=plan.scopes[0],
            workflow_by_slot=_workflow_by_slot(plan),
        )
        renderer._provider_dependency_expression(
            workflow=workflow,
            dependency_plan=dependency_plan,
            is_async_call=False,
            context=context,
            workflow_by_slot=_workflow_by_slot(plan),
        )


def test_all_dependency_expression_can_inline_root_cached_dependency() -> None:
    renderer = ResolversTemplateRenderer()
    plan = _plan_for_renderer()
    workflow = plan.workflows[0]
    parameter = inspect.Parameter(
        "dep",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    dependency = ProviderDependency(
        provides=int,
        parameter=parameter,
    )
    dependency_plan = ProviderDependencyPlan(
        kind="all",
        dependency=dependency,
        dependency_index=0,
        all_slots=(workflow.slot,),
    )
    context = DependencyExpressionContext(
        class_scope_level=Scope.REQUEST.level,
        root_scope=plan.scopes[0],
        root_resolver_expression="_root_resolver",
        workflow_by_slot=_workflow_by_slot(plan),
    )

    expression = renderer._all_dependency_expression(
        dependency_plan=dependency_plan,
        is_async_call=False,
        context=context,
        workflow_by_slot=_workflow_by_slot(plan),
    )

    assert "_root_resolver" in expression


def test_dependency_expression_for_plan_raises_for_omit_plan() -> None:
    renderer = ResolversTemplateRenderer()
    plan = _plan_for_renderer()
    workflow = plan.workflows[0]
    parameter = inspect.Parameter(
        "dep",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    dependency = ProviderDependency(
        provides=int,
        parameter=parameter,
    )
    dependency_plan = ProviderDependencyPlan(
        kind="omit",
        dependency=dependency,
        dependency_index=0,
    )

    with pytest.raises(ValueError, match="has no expression"):
        renderer._dependency_expression_for_plan(
            workflow=workflow,
            dependency_plan=dependency_plan,
            is_async_call=False,
            context=DependencyExpressionContext(
                class_scope_level=plan.scopes[0].scope_level,
                root_scope=plan.scopes[0],
                workflow_by_slot=_workflow_by_slot(plan),
            ),
            workflow_by_slot=_workflow_by_slot(plan),
        )


def test_dependency_expression_for_plan_raises_for_literal_plan_without_expression() -> None:
    renderer = ResolversTemplateRenderer()
    plan = _plan_for_renderer()
    workflow = plan.workflows[0]
    parameter = inspect.Parameter(
        "dep",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    dependency = ProviderDependency(
        provides=int,
        parameter=parameter,
    )
    dependency_plan = ProviderDependencyPlan(
        kind="literal",
        dependency=dependency,
        dependency_index=0,
        literal_expression=None,
    )

    with pytest.raises(ValueError, match="missing literal expression"):
        renderer._dependency_expression_for_plan(
            workflow=workflow,
            dependency_plan=dependency_plan,
            is_async_call=False,
            context=DependencyExpressionContext(
                class_scope_level=plan.scopes[0].scope_level,
                root_scope=plan.scopes[0],
                workflow_by_slot=_workflow_by_slot(plan),
            ),
            workflow_by_slot=_workflow_by_slot(plan),
        )


def test_dependency_expression_for_plan_returns_literal_expression() -> None:
    renderer = ResolversTemplateRenderer()
    plan = _plan_for_renderer()
    workflow = plan.workflows[0]
    parameter = inspect.Parameter(
        "dep",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    dependency = ProviderDependency(
        provides=int,
        parameter=parameter,
    )
    dependency_plan = ProviderDependencyPlan(
        kind="literal",
        dependency=dependency,
        dependency_index=0,
        literal_expression="None",
    )

    expression = renderer._dependency_expression_for_plan(
        workflow=workflow,
        dependency_plan=dependency_plan,
        is_async_call=False,
        context=DependencyExpressionContext(
            class_scope_level=plan.scopes[0].scope_level,
            root_scope=plan.scopes[0],
            workflow_by_slot=_workflow_by_slot(plan),
        ),
        workflow_by_slot=_workflow_by_slot(plan),
    )

    assert expression == "None"


def test_inline_root_dependency_expression_for_plan_covers_all_new_plan_kinds() -> None:
    renderer = ResolversTemplateRenderer()
    plan = _plan_for_renderer()
    context = DependencyExpressionContext(
        class_scope_level=plan.scopes[0].scope_level,
        root_scope=plan.scopes[0],
        workflow_by_slot=_workflow_by_slot(plan),
    )
    parameter = inspect.Parameter(
        "dep",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    dependency = ProviderDependency(
        provides=int,
        parameter=parameter,
    )

    omit_plan = ProviderDependencyPlan(
        kind="omit",
        dependency=dependency,
        dependency_index=0,
    )
    literal_plan = ProviderDependencyPlan(
        kind="literal",
        dependency=dependency,
        dependency_index=0,
        literal_expression="None",
    )
    provider_handle_missing_slot_plan = ProviderDependencyPlan(
        kind="provider_handle",
        dependency=dependency,
        dependency_index=0,
        provider_inner_slot=None,
    )
    provider_handle_sync_plan = ProviderDependencyPlan(
        kind="provider_handle",
        dependency=dependency,
        dependency_index=0,
        provider_inner_slot=1,
        provider_is_async=False,
    )
    provider_handle_async_plan = ProviderDependencyPlan(
        kind="provider_handle",
        dependency=dependency,
        dependency_index=0,
        provider_inner_slot=1,
        provider_is_async=True,
    )
    context_missing_key_plan = ProviderDependencyPlan(
        kind="context",
        dependency=dependency,
        dependency_index=0,
        ctx_key_global_name=None,
    )
    context_key_plan = ProviderDependencyPlan(
        kind="context",
        dependency=dependency,
        dependency_index=0,
        ctx_key_global_name="_ctx_1_0_key",
    )
    provider_missing_slot_plan = ProviderDependencyPlan(
        kind="provider",
        dependency=dependency,
        dependency_index=0,
        dependency_slot=None,
    )

    assert (
        renderer._inline_root_dependency_expression_for_plan(
            dependency_plan=omit_plan,
            context=context,
            depth=0,
        )
        is renderer_module._OMIT_INLINE_ARGUMENT
    )
    assert (
        renderer._inline_root_dependency_expression_for_plan(
            dependency_plan=literal_plan,
            context=context,
            depth=0,
        )
        == "None"
    )
    assert (
        renderer._inline_root_dependency_expression_for_plan(
            dependency_plan=provider_handle_missing_slot_plan,
            context=context,
            depth=0,
        )
        is None
    )
    assert (
        renderer._inline_root_dependency_expression_for_plan(
            dependency_plan=provider_handle_sync_plan,
            context=context,
            depth=0,
        )
        == "lambda: self._root_resolver.resolve_1()"
    )
    assert (
        renderer._inline_root_dependency_expression_for_plan(
            dependency_plan=provider_handle_async_plan,
            context=context,
            depth=0,
        )
        == "lambda: self._root_resolver.aresolve_1()"
    )
    assert (
        renderer._inline_root_dependency_expression_for_plan(
            dependency_plan=context_missing_key_plan,
            context=context,
            depth=0,
        )
        is None
    )
    assert (
        renderer._inline_root_dependency_expression_for_plan(
            dependency_plan=context_key_plan,
            context=context,
            depth=0,
        )
        == "self._root_resolver._resolve_from_context(_ctx_1_0_key)"
    )
    assert (
        renderer._inline_root_dependency_expression_for_plan(
            dependency_plan=provider_missing_slot_plan,
            context=context,
            depth=0,
        )
        is None
    )
