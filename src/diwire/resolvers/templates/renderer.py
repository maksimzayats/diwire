from typing import TypedDict

from jinja2 import Environment

from diwire.providers import ProvidersRegistrations
from diwire.resolvers.templates.templates import RESOLVERS_CODE_TEMPLATE
from diwire.scope import BaseScope, Scope, Scopes


class RenderContext(TypedDict):
    """Context for rendering resolver templates."""

    root_scope: BaseScope
    """The root scope. Used to identify the top-level scope.

    The singletons and transient registrations will be rendered in the root resolver.
    """

    scopes: Scopes
    """An enum-like class representing different scopes."""

    registrations: ProvidersRegistrations
    """A registry of provider registrations."""


class ResolversTemplateRenderer:
    """Renderer for resolver templates."""

    def __init__(self) -> None:
        self._env = Environment(autoescape=True)
        self._root_template = self._env.from_string(RESOLVERS_CODE_TEMPLATE)

    def render(
        self,
        root_scope: BaseScope,
    ) -> str:
        """Render the resolver template with the given context."""
        context = RenderContext(
            scopes=root_scope.owner,
            registrations=root_scope,
        )
        return self._root_template.render(**context)


def main() -> None:
    renderer = ResolversTemplateRenderer()
    rendered_code = renderer.render(
        Scope=Scope,
        registrations=ProvidersRegistrations(),
    )
    print(rendered_code)  # noqa: T201


if __name__ == "__main__":
    main()
