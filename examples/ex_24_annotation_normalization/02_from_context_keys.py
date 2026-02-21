"""FromContext keys also ignore non-component Annotated metadata."""

from __future__ import annotations

from typing import Annotated, TypeAlias

from diwire import Component, Container, FromContext, Scope

Priority: TypeAlias = Annotated[int, Component("priority")]
PriorityWithMeta: TypeAlias = Annotated[int, Component("priority"), "meta"]


def main() -> None:
    container = Container()

    with container.enter_scope(
        Scope.REQUEST,
        context={
            int: 7,
            Priority: 42,
        },
    ) as request_scope:
        plain = request_scope.resolve(FromContext[Annotated[int, "request-id"]])
        component = request_scope.resolve(FromContext[PriorityWithMeta])

    print(f"plain={plain}")  # => plain=7
    print(f"component={component}")  # => component=42


if __name__ == "__main__":
    main()
