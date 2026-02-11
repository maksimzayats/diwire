"""Focused example: ``register_instance`` for pre-built objects."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container


@dataclass(slots=True)
class Config:
    value: str


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    config = Config(value="singleton")
    container.register_instance(Config, instance=config)

    first = container.resolve(Config)
    second = container.resolve(Config)
    print(f"instance_singleton={first is second}")  # => instance_singleton=True


if __name__ == "__main__":
    main()
