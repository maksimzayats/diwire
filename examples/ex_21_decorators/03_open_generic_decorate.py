"""Open-generic decoration.

This example decorates ``Repo[T]`` and resolves multiple closed keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from diwire import Container

T = TypeVar("T")


class Repo(Generic[T]):
    pass


@dataclass(slots=True)
class SqlRepo(Repo[T]):
    model: type[T]


@dataclass(slots=True)
class TimedRepo(Repo[T]):
    inner: Repo[T]


def build_repo(model: type[T]) -> Repo[T]:
    return SqlRepo(model=model)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(build_repo, provides=Repo[T])
    container.decorate(provides=Repo[T], decorator=TimedRepo)

    int_repo = container.resolve(Repo[int])
    str_repo = container.resolve(Repo[str])

    print(type(int_repo).__name__)
    print(type(int_repo.inner).__name__)
    print(type(str_repo.inner).__name__)
    print(int_repo.inner.model is int)
    print(str_repo.inner.model is str)


if __name__ == "__main__":
    main()
