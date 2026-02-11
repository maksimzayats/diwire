"""Focused example: ``NamedTuple`` dependency extraction."""

from __future__ import annotations

from typing import NamedTuple

from diwire import Container


class Dependency:
    pass


class Consumer(NamedTuple):
    dependency: Dependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    dependency = Dependency()
    container.add_instance(dependency)
    container.add_concrete(Consumer)

    print(
        f"namedtuple_ok={container.resolve(Consumer).dependency is dependency}",
    )  # => namedtuple_ok=True


if __name__ == "__main__":
    main()
