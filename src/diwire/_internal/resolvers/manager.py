from typing import Any, cast

from diwire._internal.providers import ProvidersRegistrations
from diwire._internal.resolvers.protocol import BuildRootResolverFunctionProtocol, ResolverProtocol
from diwire._internal.resolvers.templates.planner import validate_resolver_assembly_managed_scopes
from diwire._internal.resolvers.templates.renderer import ResolversTemplateRenderer
from diwire._internal.scope import BaseScope


class ResolversManager:
    """Manager for dependency resolvers."""

    def __init__(self) -> None:
        self._template_renderer = ResolversTemplateRenderer()

    def build_root_resolver(
        self,
        root_scope: BaseScope,
        registrations: ProvidersRegistrations,
    ) -> ResolverProtocol:
        """Get the root resolver for the given registrations.

        Generates the resolver code dynamically based on the provided registrations and root scope.

        Args:
            root_scope: Root scope used to initialize the resolver.
            registrations: Provider registrations used to build resolver instances or generated code.

        """
        validate_resolver_assembly_managed_scopes(root_scope=root_scope)
        code = self._template_renderer.get_providers_code(
            root_scope=root_scope,
            registrations=registrations,
        )
        managed_scopes = validate_resolver_assembly_managed_scopes(root_scope=root_scope)

        namespace: dict[str, Any] = {}
        exec(code, namespace)  # noqa: S102

        for scope in managed_scopes:
            scope_binding_name = f"_scope_obj_{scope.level}"
            if scope_binding_name in namespace:
                namespace[scope_binding_name] = scope

        build_root_resolver = cast(
            "BuildRootResolverFunctionProtocol",
            namespace["build_root_resolver"],
        )

        return build_root_resolver(registrations)
