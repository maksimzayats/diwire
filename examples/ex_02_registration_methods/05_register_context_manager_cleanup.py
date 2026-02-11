"""Focused example: ``register_context_manager`` cleanup on scope exit."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from diwire import Container, Lifetime, Scope


class Resource:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    state = {"cleaned": False}

    @contextmanager
    def provide_resource() -> Generator[Resource, None, None]:
        try:
            yield Resource()
        finally:
            state["cleaned"] = True

    container.register_context_manager(
        Resource,
        context_manager=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(Resource)

    print(f"context_manager_cleaned={state['cleaned']}")  # => context_manager_cleaned=True


if __name__ == "__main__":
    main()
