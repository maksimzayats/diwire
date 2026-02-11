"""ContainerContext: unbound errors, replay, injection, and rebind behavior.

This module demonstrates:

1. ``DIWireContainerNotSetError`` when context is used before binding.
2. Deferred registration replay when calling ``set_current``.
3. ``@container_context.inject`` for a function and an instance method.
4. Re-binding to a new container and replaying all recorded operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Injected
from diwire.container_context import ContainerContext
from diwire.exceptions import DIWireContainerNotSetError


@dataclass(slots=True)
class Message:
    value: str


@dataclass(slots=True)
class Service:
    message: Message


def main() -> None:
    context = ContainerContext()

    try:
        context.resolve(Service)
    except DIWireContainerNotSetError as error:
        unbound_error = type(error).__name__
    print(f"unbound_error={unbound_error}")  # => unbound_error=DIWireContainerNotSetError

    context.register_instance(instance=Message(value="context-message"))
    context.register_concrete(concrete_type=Service)

    first_container = Container(autoregister_concrete_types=False)
    context.set_current(first_container)
    replay_ok = first_container.resolve(Service).message.value == "context-message"
    print(f"replay_ok={replay_ok}")  # => replay_ok=True

    @context.inject
    def read_message(message: Injected[Message]) -> str:
        return message.value

    print(f"inject_function_ok={read_message() == 'context-message'}")  # => inject_function_ok=True

    class Handler:
        @context.inject
        def read(self, message: Injected[Message]) -> str:
            return message.value

    handler = Handler()
    print(f"inject_method_ok={handler.read() == 'context-message'}")  # => inject_method_ok=True

    second_container = Container(autoregister_concrete_types=False)
    context.set_current(second_container)
    rebind_replays = second_container.resolve(Service).message.value == "context-message"
    print(f"rebind_replays={rebind_replays}")  # => rebind_replays=True


if __name__ == "__main__":
    main()
