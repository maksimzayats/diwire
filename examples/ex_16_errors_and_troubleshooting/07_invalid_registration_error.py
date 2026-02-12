"""Focused example: ``DIWireInvalidRegistrationError``."""

from __future__ import annotations

from typing import Any, cast

from diwire import Container, DIWireInvalidRegistrationError


def main() -> None:
    container = Container()

    try:
        container.add_instance(object(), provides=cast("Any", None))
    except DIWireInvalidRegistrationError as error:
        error_name = type(error).__name__

    print(f"invalid_reg={error_name}")  # => invalid_reg=DIWireInvalidRegistrationError


if __name__ == "__main__":
    main()
