from __future__ import annotations

import inspect

import pytest

from diwire import Container, Scope
from diwire.providers import ProviderDependency
from diwire.resolvers.templates.planner import (
    ProviderDependencyPlan,
    ProviderWorkflowPlan,
    ResolverGenerationPlan,
    ResolverGenerationPlanner,
)
from diwire.resolvers.templates.renderer import (
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
