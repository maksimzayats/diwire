"""Passing __diwire_context without opening a scope raises a clear error."""

from __future__ import annotations

from diwire import Container, FromContext
from diwire.exceptions import DIWireInvalidRegistrationError


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    @container.inject(auto_open_scope=False)
    def handler(value: FromContext[int]) -> int:
        return value

    try:
        handler(__diwire_context={int: 7})
    except DIWireInvalidRegistrationError as error:
        print(type(error).__name__)


if __name__ == "__main__":
    main()
