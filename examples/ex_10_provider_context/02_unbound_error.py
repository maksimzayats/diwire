"""Focused example: unbound ``ProviderContext`` usage error."""

from __future__ import annotations

from diwire import ProviderContext
from diwire.exceptions import DIWireProviderNotSetError


def main() -> None:
    context = ProviderContext()

    try:
        context.resolve(str)
    except DIWireProviderNotSetError as error:
        print(f"unbound_error={type(error).__name__}")  # => unbound_error=DIWireProviderNotSetError


if __name__ == "__main__":
    main()
