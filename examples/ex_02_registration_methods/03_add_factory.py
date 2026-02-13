"""Focused example: ``add_factory`` for custom build logic."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Lifetime


@dataclass(slots=True)
class Service:
    value: str


def main() -> None:
    container = Container()
    build_state = {"count": 0}

    def build_service() -> Service:
        build_state["count"] += 1
        return Service(value=f"built-{build_state['count']}")

    container.add_factory(
        build_service,
        provides=Service,
        lifetime=Lifetime.TRANSIENT,
    )

    first = container.resolve(Service)
    second = container.resolve(Service)
    print(f"factory_custom_logic={first.value}")  # => factory_custom_logic=built-1
    print(f"factory_is_transient={first is not second}")  # => factory_is_transient=True


if __name__ == "__main__":
    main()
