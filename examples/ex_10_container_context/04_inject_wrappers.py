"""Focused example: ``@container_context.inject`` on function and method."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Injected
from diwire.container_context import ContainerContext


@dataclass(slots=True)
class Message:
    value: str


def main() -> None:
    context = ContainerContext()
    context.register_instance(instance=Message(value="context-message"))
    context.set_current(Container(autoregister_concrete_types=False))

    @context.inject
    def read_function(message: Injected[Message]) -> str:
        return message.value

    class Reader:
        @context.inject
        def read_method(self, message: Injected[Message]) -> str:
            return message.value

    print(
        f"inject_function_ok={read_function() == 'context-message'}",
    )  # => inject_function_ok=True
    print(
        f"inject_method_ok={Reader().read_method() == 'context-message'}",
    )  # => inject_method_ok=True


if __name__ == "__main__":
    main()
