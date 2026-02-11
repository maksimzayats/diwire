"""Focused example: dataclass constructor dependency extraction."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container


@dataclass(slots=True)
class Dependency:
    name: str


@dataclass(slots=True)
class Consumer:
    dependency: Dependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    dependency = Dependency(name="framework")
    container.register_instance(instance=dependency)
    container.register_concrete(concrete_type=Consumer)

    print(
        f"dataclass_ok={container.resolve(Consumer).dependency is dependency}",
    )  # => dataclass_ok=True


if __name__ == "__main__":
    main()
