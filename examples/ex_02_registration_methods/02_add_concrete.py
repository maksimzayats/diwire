"""Focused example: ``add_concrete`` for constructor-based creation."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container


class Dependency:
    pass


@dataclass(slots=True)
class Service:
    dependency: Dependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(Dependency, provides=Dependency)
    container.add_concrete(Service, provides=Service)

    resolved = container.resolve(Service)
    print(
        f"concrete_injected_dep={isinstance(resolved.dependency, Dependency)}",
    )  # => concrete_injected_dep=True


if __name__ == "__main__":
    main()
