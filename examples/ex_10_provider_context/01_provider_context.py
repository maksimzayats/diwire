"""ProviderContext: unbound errors, fallback injection, and bound resolver precedence."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Injected, ProviderContext
from diwire.exceptions import DIWireProviderNotSetError


@dataclass(slots=True)
class Message:
    value: str


def main() -> None:
    context = ProviderContext()

    try:
        context.resolve(Message)
    except DIWireProviderNotSetError as error:
        print(f"unbound_error={type(error).__name__}")  # => unbound_error=DIWireProviderNotSetError

    first = Container(provider_context=context, autoregister_concrete_types=False)
    first.add_instance(Message("first"), provides=Message)

    second = Container(provider_context=context, autoregister_concrete_types=False)
    second.add_instance(Message("second"), provides=Message)

    @context.inject
    def read_message(message: Injected[Message]) -> str:
        return message.value

    print(f"fallback_last_wins={read_message() == 'second'}")  # => fallback_last_wins=True

    with first.compile():
        print(f"bound_precedence={read_message() == 'first'}")  # => bound_precedence=True


if __name__ == "__main__":
    main()
