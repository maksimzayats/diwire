"""Focused example: ``register_concrete`` and ``register_factory`` together."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container


class ConcreteDependency:
    pass


@dataclass(slots=True)
class FactoryService:
    dependency: ConcreteDependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.register_concrete(ConcreteDependency, concrete_type=ConcreteDependency)

    def build_service(dependency: ConcreteDependency) -> FactoryService:
        return FactoryService(dependency=dependency)

    container.register_factory(FactoryService, factory=build_service)
    resolved = container.resolve(FactoryService)
    print(
        f"factory_injected_dep={isinstance(resolved.dependency, ConcreteDependency)}",
    )  # => factory_injected_dep=True


if __name__ == "__main__":
    main()
