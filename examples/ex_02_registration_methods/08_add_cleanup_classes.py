"""Focused example: provider classes that keep setup and cleanup together."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from diwire import Container, Injected, Lifetime, Scope


@dataclass(kw_only=True)
class State:
    generator_cleaned: bool = False
    context_manager_cleaned: bool = False


class GeneratorResource:
    pass


class ContextManagerResource:
    pass


@dataclass(kw_only=True)
class GeneratorResourceFactory:
    state: Injected[State]

    def __call__(self) -> Generator[GeneratorResource, None, None]:
        try:
            yield GeneratorResource()
        finally:
            self.state.generator_cleaned = True


@dataclass(kw_only=True)
class ContextManagerResourceFactory:
    state: Injected[State]

    @contextmanager
    def __call__(self) -> Generator[ContextManagerResource, None, None]:
        try:
            yield ContextManagerResource()
        finally:
            self.state.context_manager_cleaned = True


def main() -> None:
    container = Container()
    state = State()

    container.add_instance(state)
    container.add_generator_class(
        GeneratorResourceFactory,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add_context_manager_class(
        ContextManagerResourceFactory,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(GeneratorResource)
        _ = request_scope.resolve(ContextManagerResource)

    print(
        f"generator_class_cleaned={state.generator_cleaned}",
    )  # => generator_class_cleaned=True
    print(
        f"context_manager_class_cleaned={state.context_manager_cleaned}",
    )  # => context_manager_class_cleaned=True


if __name__ == "__main__":
    main()
