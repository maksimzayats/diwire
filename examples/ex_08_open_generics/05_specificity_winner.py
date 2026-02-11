"""Focused example: most-specific open template selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from diwire import Container

T = TypeVar("T")
U = TypeVar("U")


class Repo(Generic[T]):
    pass


@dataclass(slots=True)
class GenericRepo(Repo[T]):
    dependency_type: type[T]


@dataclass(slots=True)
class ListRepo(Repo[list[U]]):
    item_type: type[U]


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(GenericRepo, provides=Repo)
    container.add_concrete(ListRepo, provides=Repo[list[U]])

    resolved = cast("ListRepo[int]", container.resolve(Repo[list[int]]))
    print(f"specificity_item={resolved.item_type.__name__}")  # => specificity_item=int


if __name__ == "__main__":
    main()
