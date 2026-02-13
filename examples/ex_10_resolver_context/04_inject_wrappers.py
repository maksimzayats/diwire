"""Focused example: ``@resolver_context.inject`` on function and method."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Injected, resolver_context


@dataclass(slots=True)
class Message:
    value: str


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(Message(value="context-message"), provides=Message)

    @resolver_context.inject
    def read_function(message: Injected[Message]) -> str:
        return message.value

    class Handler:
        @resolver_context.inject
        def read_method(self, message: Injected[Message]) -> str:
            return message.value

    handler = Handler()

    print(
        f"inject_function_ok={read_function() == 'context-message'}"
    )  # => inject_function_ok=True
    print(
        f"inject_method_ok={handler.read_method() == 'context-message'}"
    )  # => inject_method_ok=True


if __name__ == "__main__":
    main()
