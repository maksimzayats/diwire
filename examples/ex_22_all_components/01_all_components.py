"""Resolve all implementations with ``All[T]`` (base + components).

This module demonstrates how to collect a plugin stack by combining:

- the plain registration for a base type ``T`` (if present), and
- all component registrations keyed as ``Annotated[T, Component(...)]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Protocol, TypeAlias

from diwire import All, Component, Container, Injected, resolver_context


class EventHandler(Protocol):
    def handle(self, event: str) -> str: ...


@dataclass(frozen=True, slots=True)
class BaseHandler:
    def handle(self, event: str) -> str:
        return f"base:{event}"


@dataclass(frozen=True, slots=True)
class LoggingHandler:
    def handle(self, event: str) -> str:
        return f"logging:{event}"


@dataclass(frozen=True, slots=True)
class MetricsHandler:
    def handle(self, event: str) -> str:
        return f"metrics:{event}"


Logging: TypeAlias = Annotated[EventHandler, Component("logging")]
Metrics: TypeAlias = Annotated[EventHandler, Component("metrics")]


def main() -> None:
    container = Container()

    container.add(BaseHandler, provides=EventHandler)
    container.add(LoggingHandler, provides=Logging)
    container.add(MetricsHandler, provides=Metrics)

    handlers = container.resolve(All[EventHandler])
    print(
        [handler.handle("evt") for handler in handlers],
    )  # => ['base:evt', 'logging:evt', 'metrics:evt']

    @resolver_context.inject
    def dispatch(event: str, handlers: Injected[All[EventHandler]]) -> tuple[str, ...]:
        return tuple(handler.handle(event) for handler in handlers)

    print(dispatch("evt"))  # => ('base:evt', 'logging:evt', 'metrics:evt')


if __name__ == "__main__":
    main()
