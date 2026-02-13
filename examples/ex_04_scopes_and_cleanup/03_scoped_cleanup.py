"""Focused example: scoped resource cleanup on scope exit."""

from __future__ import annotations

from collections.abc import Generator

from diwire import Container, Lifetime, Scope


class ScopedResource:
    pass


def main() -> None:
    container = Container()
    state = {"closed": 0}

    def provide_resource() -> Generator[ScopedResource, None, None]:
        try:
            yield ScopedResource()
        finally:
            state["closed"] += 1

    container.add_generator(
        provide_resource,
        provides=ScopedResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(ScopedResource)
        closed_inside_scope = state["closed"]

    closed_after_exit = state["closed"]
    print(
        f"scoped_cleanup_after_exit={closed_inside_scope == 0 and closed_after_exit == 1}",
    )  # => scoped_cleanup_after_exit=True


if __name__ == "__main__":
    main()
