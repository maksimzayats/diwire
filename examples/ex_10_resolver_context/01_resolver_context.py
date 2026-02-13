"""ResolverContext: unbound errors, fallback resolution/scope/injection, and bound precedence."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Injected, ResolverContext, Scope
from diwire.exceptions import DIWireResolverNotSetError


@dataclass(slots=True)
class Message:
    value: str


def main() -> None:
    context = ResolverContext()

    try:
        context.resolve(Message)
    except DIWireResolverNotSetError as error:
        print(f"unbound_error={type(error).__name__}")  # => unbound_error=DIWireResolverNotSetError

    first = Container(resolver_context=context, autoregister_concrete_types=False)
    first.add_instance(Message("first"), provides=Message)

    second = Container(resolver_context=context, autoregister_concrete_types=False)
    second.add_instance(Message("second"), provides=Message)

    print(
        f"fallback_resolve={context.resolve(Message).value == 'second'}"
    )  # => fallback_resolve=True
    with context.enter_scope(Scope.REQUEST) as request_scope:
        print(
            f"fallback_enter_scope={request_scope.resolve(Message).value == 'second'}"
        )  # => fallback_enter_scope=True

    @context.inject
    def read_message(message: Injected[Message]) -> str:
        return message.value

    print(f"fallback_last_wins={read_message() == 'second'}")  # => fallback_last_wins=True

    with first.compile():
        print(f"bound_precedence={read_message() == 'first'}")  # => bound_precedence=True


if __name__ == "__main__":
    main()
