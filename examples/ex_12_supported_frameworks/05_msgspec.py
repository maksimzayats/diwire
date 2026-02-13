"""Focused example: ``msgspec.Struct`` field dependency extraction."""

from __future__ import annotations

import msgspec

from diwire import Container


class Dependency:
    pass


class Consumer(msgspec.Struct):
    dependency: Dependency


def main() -> None:
    container = Container()
    dependency = Dependency()
    container.add_instance(dependency)
    container.add(Consumer)

    print(
        f"msgspec_ok={container.resolve(Consumer).dependency is dependency}",
    )  # => msgspec_ok=True


if __name__ == "__main__":
    main()
