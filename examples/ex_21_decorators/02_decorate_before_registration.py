"""Two readability-focused patterns.

1. ``decorate(...)`` can be called before ``add_*``.
2. ``inner_parameter=...`` removes ambiguity when inference is unclear.
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
    # Pattern A: decorate first, register later.
    container = Container(autoregister_concrete_types=False)
    container.decorate(
        provides=PrimaryRepo,
        decorator=CachedRepo,
        inner_parameter="inner",
    )
    container.add_concrete(SqlRepo, provides=PrimaryRepo)

    decorated = container.resolve(PrimaryRepo)
    print(f"pattern_a_outer={type(decorated).__name__}")
    print(f"pattern_a_inner={type(decorated.inner).__name__}")
    print(f"pattern_a_result={decorated.get('account-42')}")

    # Pattern B: ambiguous decorator needs explicit inner_parameter.
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
    print(f"pattern_b_error={ambiguous_error}")
    print(f"pattern_b_outer={type(resolved).__name__}")
    print(f"pattern_b_inner={type(resolved.first).__name__}")


if __name__ == "__main__":
    main()
