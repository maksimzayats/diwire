from typing import Any, cast

from diwire.providers import ProvidersRegistrations
from diwire.resolvers.protocol import BuildRootResolverFunctionProtocol, ResolverProtocol
from diwire.resolvers.templates.renderer import ResolversTemplateRenderer
from diwire.scope import BaseScope


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
        """
        code = self._template_renderer.get_providers_code(
            root_scope=root_scope,
            registrations=registrations,
        )

        namespace: dict[str, Any] = {}
        exec(code, namespace)  # noqa: S102

        build_root_resolver = cast(
            "BuildRootResolverFunctionProtocol",
            namespace["build_root_resolver"],
        )

        return build_root_resolver(registrations)
