"""Focused example: closed generic override beats open template."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from diwire import Container

T = TypeVar("T")


class IBox(Generic[T]):
    pass


@dataclass(slots=True)
class Box(IBox[T]):
    type_arg: type[T]


class _SpecialIntBox(IBox[int]):
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(Box, provides=IBox)
    container.add_concrete(_SpecialIntBox, provides=IBox[int])

    resolved = container.resolve(IBox[int])
    print(f"override={type(resolved).__name__}")  # => override=_SpecialIntBox


if __name__ == "__main__":
    main()
