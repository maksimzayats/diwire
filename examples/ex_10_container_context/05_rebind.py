"""Focused example: rebinding replays all stored operations."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container
from diwire.container_context import ContainerContext


@dataclass(slots=True)
class Message:
    value: str


@dataclass(slots=True)
class Service:
    message: Message


def main() -> None:
    context = ContainerContext()
    context.add_instance(Message(value="context-message"))
    context.add_concrete(Service)

    first = Container(autoregister_concrete_types=False)
    context.set_current(first)

    second = Container(autoregister_concrete_types=False)
    context.set_current(second)

    print(
        f"rebind_replays={second.resolve(Service).message.value == 'context-message'}",
    )  # => rebind_replays=True


if __name__ == "__main__":
    main()
