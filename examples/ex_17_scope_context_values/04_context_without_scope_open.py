"""Passing diwire_context without opening a scope raises a clear error."""

from __future__ import annotations

from diwire import Container, FromContext, resolver_context
from diwire.exceptions import DIWireInvalidRegistrationError


def main() -> None:
    Container(autoregister_concrete_types=False)

    @resolver_context.inject(auto_open_scope=False)
    def handler(value: FromContext[int]) -> int:
        return value

    try:
        handler(diwire_context={int: 7})
    except DIWireInvalidRegistrationError as error:
        print(type(error).__name__)


if __name__ == "__main__":
    main()
