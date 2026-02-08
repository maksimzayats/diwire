from dataclasses import dataclass, field
from typing import Iterator


class BaseScope(int):
    def __set_name__(self, owner, name):
        self.scope_name = name

    def __repr__(self) -> str:
        return f"Scope.{self.scope_name}({int(self)})"


@dataclass(slots=True, frozen=True)
class Scopes:
    """Enum like class for scopes."""

    RUNTIME: BaseScope = field(init=False, default=BaseScope(0))
    APP: BaseScope = field(init=False, default=BaseScope(1))
    SESSION: BaseScope = field(init=False, default=BaseScope(2))
    REQUEST: BaseScope = field(init=False, default=BaseScope(3))
    ACTION: BaseScope = field(init=False, default=BaseScope(4))
    STEP: BaseScope = field(init=False, default=BaseScope(5))

    def __iter__(self) -> Iterator[BaseScope]:
        yield self.RUNTIME
        yield self.APP
        yield self.SESSION
        yield self.REQUEST
        yield self.ACTION
        yield self.STEP

    @property
    def skippable(self) -> Iterator[BaseScope]:
        """Generate all skippable scopes."""
        yield self.RUNTIME
        yield self.SESSION


Scope = Scopes()
"""Enum like instance for scopes."""
