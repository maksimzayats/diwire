"""Decorate before registration and use explicit ``inner_parameter``.

Highlights:

1. Register a decoration rule before the base provider exists.
2. Decorate an ``Annotated`` key while the wrapper keeps ``inner`` typed as base protocol.
3. Handle ambiguous inner-parameter inference with an explicit parameter name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from diwire import Component, Container
from diwire.exceptions import DIWireInvalidRegistrationError


class Repo:
    def get(self, key: str) -> str:
        raise NotImplementedError


class SqlRepo(Repo):
    def get(self, key: str) -> str:
        return f"sql:{key}"


PrimaryRepo = Annotated[Repo, Component("primary")]


@dataclass(slots=True)
class CachedRepo(Repo):
    inner: Repo
    cache_hits: int = 0

    def get(self, key: str) -> str:
        self.cache_hits += 1
        return self.inner.get(key)


class AmbiguousDecorator(Repo):
    def __init__(self, first: Repo, second: Repo) -> None:
        self.first = first
        self.second = second

    def get(self, key: str) -> str:
        return self.first.get(key)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.decorate(
        provides=PrimaryRepo,
        decorator=CachedRepo,
        inner_parameter="inner",
    )
    container.add_concrete(SqlRepo, provides=PrimaryRepo)

    decorated = container.resolve(PrimaryRepo)
    print(type(decorated).__name__)
    print(type(decorated.inner).__name__)
    print(decorated.get("account-42"))

    ambiguous_error: str
    try:
        container.decorate(provides=Repo, decorator=AmbiguousDecorator)
    except DIWireInvalidRegistrationError as error:
        ambiguous_error = type(error).__name__
    print(ambiguous_error)

    container.decorate(
        provides=Repo,
        decorator=AmbiguousDecorator,
        inner_parameter="first",
    )
    container.add_concrete(SqlRepo, provides=Repo)
    resolved = container.resolve(Repo)
    print(type(resolved).__name__)
    print(type(resolved.first).__name__)


if __name__ == "__main__":
    main()
