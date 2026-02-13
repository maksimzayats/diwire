"""Open-generic decoration in one screen.

Register once for ``Repo[T]``, decorate once, then resolve many closed types.
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
    container = Container()
    container.add_factory(build_repo, provides=Repo)
    container.decorate(provides=Repo, decorator=TimedRepo)

    int_repo = container.resolve(Repo[int])
    str_repo = container.resolve(Repo[str])

    print(f"outer_type={type(int_repo).__name__}")  # => outer_type=TimedRepo
    print(f"int_inner_type={type(int_repo.inner).__name__}")  # => int_inner_type=SqlRepo
    print(f"str_inner_type={type(str_repo.inner).__name__}")  # => str_inner_type=SqlRepo
    print(f"int_model_ok={int_repo.inner.model is int}")  # => int_model_ok=True
    print(f"str_model_ok={str_repo.inner.model is str}")  # => str_model_ok=True


if __name__ == "__main__":
    main()
