"""Focused example: ``attrs.define`` dependency extraction."""

from __future__ import annotations

import attrs

from diwire import Container


class Dependency:
    pass


@attrs.define
class Consumer:
    dependency: Dependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    dependency = Dependency()
    container.add_instance(dependency)
    container.add_concrete(Consumer)

    print(f"attrs_ok={container.resolve(Consumer).dependency is dependency}")  # => attrs_ok=True


if __name__ == "__main__":
    main()
