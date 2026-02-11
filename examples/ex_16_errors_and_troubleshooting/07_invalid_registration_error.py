"""Focused example: ``DIWireInvalidRegistrationError``."""

from __future__ import annotations

from typing import Any, cast

from diwire import Container
from diwire.exceptions import DIWireInvalidRegistrationError


def main() -> None:
    container = Container()

    try:
        container.register_instance(provides=cast("Any", None), instance=object())
    except DIWireInvalidRegistrationError as error:
        error_name = type(error).__name__

    print(f"invalid_reg={error_name}")  # => invalid_reg=DIWireInvalidRegistrationError


if __name__ == "__main__":
    main()
