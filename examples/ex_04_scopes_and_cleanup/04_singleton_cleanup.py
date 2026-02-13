"""Focused example: singleton generator cleanup on ``container.close()``."""

from __future__ import annotations

from collections.abc import Generator

from diwire import Container, Lifetime, Scope


class SingletonResource:
    pass


def main() -> None:
    container = Container()
    state = {"closed": 0}

    def provide_resource() -> Generator[SingletonResource, None, None]:
        try:
            yield SingletonResource()
        finally:
            state["closed"] += 1

    container.add_generator(
        provide_resource,
        provides=SingletonResource,
        scope=Scope.APP,
        lifetime=Lifetime.SCOPED,
    )

    _ = container.resolve(SingletonResource)
    closed_before = state["closed"]
    container.close()
    print(
        f"singleton_cleanup_on_close={closed_before == 0 and state['closed'] == 1}",
    )  # => singleton_cleanup_on_close=True


if __name__ == "__main__":
    main()
