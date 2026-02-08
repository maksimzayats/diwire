from typing import TypedDict

from jinja2 import Environment

from diwire.providers import ProvidersRegistrations
from diwire.resolvers.templates.templates import RESOLVERS_CODE_TEMPLATE
from diwire.scope import BaseScope, BaseScopes, Scope


class RenderContext(TypedDict):
    """Context for rendering resolver templates."""

    root_scope: BaseScope
    """The root scope. Used to identify the top-level scope.

    The singletons and transient registrations will be rendered in the root resolver.
    """

    scopes: type[BaseScopes]
    """An enum-like class representing different scopes."""

    registrations: ProvidersRegistrations
    """A registry of provider registrations."""


class ResolversTemplateRenderer:
    """Renderer for resolver templates."""

    def __init__(self) -> None:
        self._env = Environment(autoescape=True)
        self._root_template = self._env.from_string(RESOLVERS_CODE_TEMPLATE)

    def get_providers_code(
        self,
        *,
        root_scope: BaseScope,
        registrations: ProvidersRegistrations,
    ) -> str:
        """Render the resolver template with the given context."""
        context = RenderContext(
            root_scope=root_scope,
            scopes=root_scope.owner,
            registrations=registrations,
        )
        return self._root_template.render(**context)


def main() -> None:
    renderer = ResolversTemplateRenderer()
    rendered_code = renderer.get_providers_code(
        root_scope=Scope.APP,
        registrations=ProvidersRegistrations(),
    )
    print(rendered_code)  # noqa: T201


if __name__ == "__main__":
    main()
