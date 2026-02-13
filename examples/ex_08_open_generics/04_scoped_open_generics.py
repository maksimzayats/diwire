"""Focused example: scoped open generics require an opened scope."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from diwire import Container, Lifetime, Scope
from diwire.exceptions import DIWireScopeMismatchError

T = TypeVar("T")


class IBox(Generic[T]):
    pass


@dataclass(slots=True)
class Box(IBox[T]):
    type_arg: type[T]


def build_box(type_arg: type[T]) -> IBox[T]:
    return Box(type_arg=type_arg)


def main() -> None:
    container = Container()
    container.add_factory(
        build_box,
        provides=IBox,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    try:
        container.resolve(IBox[int])
    except DIWireScopeMismatchError:
        requires_scope = True
    else:
        requires_scope = False

    print(f"scoped_requires_scope={requires_scope}")  # => scoped_requires_scope=True


if __name__ == "__main__":
    main()
