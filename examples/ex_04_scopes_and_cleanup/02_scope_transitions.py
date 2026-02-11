"""Focused example: default and explicit scope transitions."""

from __future__ import annotations

from diwire import Container, Lifetime, Scope


class RequestDependency:
    pass


def _resolver_scope_name(resolver: object) -> str:
    return type(resolver).__name__.removeprefix("_").removesuffix("Resolver").upper()


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(
        RequestDependency,
        provides=RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        default_scope = _resolver_scope_name(request_scope)

    with container.enter_scope(Scope.ACTION) as action_scope:
        resolved = action_scope.resolve(RequestDependency)

    print(f"enter_scope_default={default_scope}")  # => enter_scope_default=REQUEST
    print(
        f"action_scope_can_resolve_request_scoped={isinstance(resolved, RequestDependency)}",
    )  # => action_scope_can_resolve_request_scoped=True


if __name__ == "__main__":
    main()
