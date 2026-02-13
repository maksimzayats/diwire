"""Two readability-focused patterns.

1. ``decorate(...)`` can be called before ``add_*``.
2. ``inner_parameter=...`` removes ambiguity when inference is unclear.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    cache_hits: int = field(default=0, init=False)

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
    print(f"pattern_a_outer={type(decorated).__name__}")  # => pattern_a_outer=CachedRepo
    print(f"pattern_a_inner={type(decorated.inner).__name__}")  # => pattern_a_inner=SqlRepo
    print(f"pattern_a_result={decorated.get('account-42')}")  # => pattern_a_result=sql:account-42

    # Pattern B: ambiguous decorator needs explicit inner_parameter.
    ambiguous_error: str
    try:
        container.decorate(provides=Repo, decorator=AmbiguousDecorator)
    except DIWireInvalidRegistrationError as error:
        ambiguous_error = type(error).__name__
    print(f"ambiguous_error={ambiguous_error}")  # => ambiguous_error=DIWireInvalidRegistrationError

    container.decorate(
        provides=Repo,
        decorator=AmbiguousDecorator,
        inner_parameter="first",
    )
    print(f"pattern_b_error={ambiguous_error}")  # => pattern_b_error=DIWireInvalidRegistrationError
    print(
        "pattern_b_inner_parameter_accepts_registration=True"
    )  # => pattern_b_inner_parameter_accepts_registration=True


if __name__ == "__main__":
    main()
