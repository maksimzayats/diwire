from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


class BaseScope(int):
    """Base class for scopes."""

    def __new__(cls, *args: Any, **_kwargs: Any) -> BaseScope:  # noqa: D102, PYI034
        return super().__new__(cls, *args)

    def __init__(self, level: int, *, skippable: bool = False) -> None:
        self.skippable = skippable
        self.level = level

    def __set_name__(
        self,
        owner: type[BaseScopes],
        name: str,
    ) -> None:
        self.owner = owner
        self.scope_name = name

    def __repr__(self) -> str:
        return f"Scope.{self.scope_name}({self.level}, skippable={self.skippable})"


@dataclass(frozen=True, kw_only=True)
class BaseScopes:
    """Base class for scopes collection."""

    skippable: tuple[BaseScope, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "skippable",
            tuple(scope for scope in self if scope.skippable),
        )

    def __iter__(self) -> Iterator[BaseScope]:
        for value in self.__dict__.values():
            if isinstance(value, BaseScope):
                yield value


@dataclass(frozen=True)
class Scopes(BaseScopes):
    """Enum like class for scopes."""

    RUNTIME: BaseScope = field(default=BaseScope(0, skippable=True))
    APP: BaseScope = field(default=BaseScope(1))
    SESSION: BaseScope = field(default=BaseScope(2, skippable=True))
    REQUEST: BaseScope = field(default=BaseScope(3))
    ACTION: BaseScope = field(default=BaseScope(4))
    STEP: BaseScope = field(default=BaseScope(5))


Scope = Scopes()
"""Enum like instance for scopes."""
