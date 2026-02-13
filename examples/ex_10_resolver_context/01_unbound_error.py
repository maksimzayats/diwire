"""Focused example: unbound ``ResolverContext`` usage error."""

from __future__ import annotations

from diwire import ResolverContext
from diwire.exceptions import DIWireResolverNotSetError


def main() -> None:
    context = ResolverContext()

    try:
        context.resolve(str)
    except DIWireResolverNotSetError as error:
        print(f"unbound_error={type(error).__name__}")  # => unbound_error=DIWireResolverNotSetError


if __name__ == "__main__":
    main()
