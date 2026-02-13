"""Focused example: ``use_resolver_context=False`` inject requires explicit resolver."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import (
    Container,
    DependencyRegistrationPolicy,
    Injected,
    MissingPolicy,
    ResolverContext,
    Scope,
)
from diwire.exceptions import DIWireResolverNotSetError


@dataclass(slots=True)
class Message:
    value: str


def _bound_self(method: object) -> object | None:
    return getattr(method, "__self__", None)


def main() -> None:
    context = ResolverContext()
    container = Container(
        missing_policy=MissingPolicy.ERROR,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
        resolver_context=context,
        use_resolver_context=False,
    )
    container.add_instance(Message("legacy"), provides=Message)

    @context.inject(scope=Scope.REQUEST)
    def read_message(message: Injected[Message]) -> str:
        return message.value

    print(
        f"fallback_resolve_ok={context.resolve(Message).value == 'legacy'}"
    )  # => fallback_resolve_ok=True

    try:
        read_message()
    except DIWireResolverNotSetError as error:
        print(
            f"inject_missing_explicit_error={type(error).__name__}"
        )  # => inject_missing_explicit_error=DIWireResolverNotSetError

    with container.enter_scope(Scope.REQUEST) as request_scope:
        print(
            f"inject_explicit_ok={read_message(diwire_resolver=request_scope) == 'legacy'}"
        )  # => inject_explicit_ok=True

    compiled = container.compile()
    print(f"rebind_enabled={_bound_self(container.resolve) is compiled}")  # => rebind_enabled=True


if __name__ == "__main__":
    main()
