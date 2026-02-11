"""Focused example: ``add_concrete`` and ``add_factory`` together."""

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
    container.add_concrete(ConcreteDependency, provides=ConcreteDependency)

    def build_service(dependency: ConcreteDependency) -> FactoryService:
        return FactoryService(dependency=dependency)

    container.add_factory(build_service, provides=FactoryService)
    resolved = container.resolve(FactoryService)
    print(
        f"factory_injected_dep={isinstance(resolved.dependency, ConcreteDependency)}",
    )  # => factory_injected_dep=True


if __name__ == "__main__":
    main()
