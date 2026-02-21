"""Non-component Annotated metadata is normalized out of dependency keys."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from diwire import Component, Container


@dataclass(slots=True)
class Service:
    source: str


def main() -> None:
    container = Container()

    container.add_instance(Service(source="base"), provides=Annotated[Service, "plain-meta"])
    container.add_instance(
        Service(source="component"),
        provides=Annotated[Service, Component("primary"), "extra-meta"],
    )

    base_direct = container.resolve(Service)
    base_annotated = container.resolve(Annotated[Service, "another-meta"])
    component_direct = container.resolve(Annotated[Service, Component("primary")])
    component_annotated = container.resolve(
        Annotated[Service, Component("primary"), "different-meta"],
    )

    print(f"base_direct={base_direct.source}")  # => base_direct=base
    print(f"base_annotated={base_annotated.source}")  # => base_annotated=base
    print(f"component_direct={component_direct.source}")  # => component_direct=component
    print(f"component_annotated={component_annotated.source}")  # => component_annotated=component


if __name__ == "__main__":
    main()
