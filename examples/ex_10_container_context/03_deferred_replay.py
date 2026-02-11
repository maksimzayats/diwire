"""Focused example: deferred registrations replay on ``set_current``."""

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
    context.register_instance(instance=Message(value="context-message"))
    context.register_concrete(concrete_type=Service)

    container = Container(autoregister_concrete_types=False)
    context.set_current(container)

    print(
        f"replay_ok={container.resolve(Service).message.value == 'context-message'}",
    )  # => replay_ok=True


if __name__ == "__main__":
    main()
