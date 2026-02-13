"""Focused example: ``add_generator`` cleanup on scope exit."""

from __future__ import annotations

from collections.abc import Generator

from diwire import Container, Lifetime, Scope


class Resource:
    pass


def main() -> None:
    container = Container()
    state = {"cleaned": False}

    def provide_resource() -> Generator[Resource, None, None]:
        try:
            yield Resource()
        finally:
            state["cleaned"] = True

    container.add_generator(
        provide_resource,
        provides=Resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(Resource)

    print(f"generator_cleaned={state['cleaned']}")  # => generator_cleaned=True


if __name__ == "__main__":
    main()
