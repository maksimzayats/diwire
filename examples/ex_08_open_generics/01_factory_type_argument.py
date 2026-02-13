"""Focused example: open generic factory with ``type[T]`` injection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from diwire import Container

T = TypeVar("T")


class IBox(Generic[T]):
    pass


@dataclass(slots=True)
class Box(IBox[T]):
    type_arg: type[T]


def build_box(type_arg: type[T]) -> IBox[T]:
    return Box(type_arg=type_arg)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(build_box, provides=IBox)

    resolved = cast("Box[int]", container.resolve(IBox[int]))
    print(f"box_int={resolved.type_arg.__name__}")  # => box_int=int


if __name__ == "__main__":
    main()
