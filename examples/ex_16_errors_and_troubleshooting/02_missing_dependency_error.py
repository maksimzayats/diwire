"""Focused example: ``DIWireDependencyNotRegisteredError``."""

from __future__ import annotations

from diwire import Container, DIWireDependencyNotRegisteredError


class MissingDependency:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    try:
        container.resolve(MissingDependency)
    except DIWireDependencyNotRegisteredError as error:
        error_name = type(error).__name__

    print(f"missing={error_name}")  # => missing=DIWireDependencyNotRegisteredError


if __name__ == "__main__":
    main()
