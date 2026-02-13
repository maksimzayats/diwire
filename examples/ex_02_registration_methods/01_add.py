"""Focused example: ``add`` for constructor-based creation."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container


class Dependency:
    pass


@dataclass(slots=True)
class Service:
    dependency: Dependency


def main() -> None:
    container = Container()
    container.add(Dependency, provides=Dependency)
    container.add(Service, provides=Service)

    resolved = container.resolve(Service)
    print(
        f"concrete_injected_dep={isinstance(resolved.dependency, Dependency)}",
    )  # => concrete_injected_dep=True


if __name__ == "__main__":
    main()
