from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


class BaseScope(int):
    """Base class for scopes."""

    def __new__(cls, *args: Any, **_kwargs: Any) -> int:  # noqa: D102
        return super().__new__(cls, *args)

    def __init__(self, level: int, *, skippable: bool = False) -> None:
        self.skippable = skippable
        self.level = level

    def __set_name__(
        self,
        owner: type[Any],
        name: str,
    ) -> None:
        self.scope_name = name

    def __repr__(self) -> str:
        return f"Scope.{self.scope_name}({self.level}, skippable={self.skippable})"


@dataclass(slots=True, frozen=True)
class Scopes:
    """Enum like class for scopes."""

    RUNTIME: BaseScope = field(init=False, default=BaseScope(0, skippable=True))
    APP: BaseScope = field(init=False, default=BaseScope(1))
    SESSION: BaseScope = field(init=False, default=BaseScope(2, skippable=True))
    REQUEST: BaseScope = field(init=False, default=BaseScope(3))
    ACTION: BaseScope = field(init=False, default=BaseScope(4))
    STEP: BaseScope = field(init=False, default=BaseScope(5))

    skippable: tuple[BaseScope, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "skippable",
            tuple(scope for scope in self if scope.skippable),
        )

    def __iter__(self) -> Iterator[BaseScope]:
        yield self.RUNTIME
        yield self.APP
        yield self.SESSION
        yield self.REQUEST
        yield self.ACTION
        yield self.STEP


Scope = Scopes()
"""Enum like instance for scopes."""
