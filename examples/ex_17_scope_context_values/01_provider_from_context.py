"""Focused example: provider dependencies can read ``FromContext[T]`` values."""

from __future__ import annotations

from diwire import Container, FromContext, Lifetime, Scope


class RequestValue:
    def __init__(self, value: int) -> None:
        self.value = value


def build_request_value(value: FromContext[int]) -> RequestValue:
    return RequestValue(value=value)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(
        build_request_value,
        provides=RequestValue,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope(Scope.REQUEST, context={int: 7}) as request_scope:
        resolved = request_scope.resolve(RequestValue)

    print(f"provider_from_context={resolved.value}")  # => provider_from_context=7


if __name__ == "__main__":
    main()
