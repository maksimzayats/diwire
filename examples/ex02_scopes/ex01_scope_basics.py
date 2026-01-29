"""Scope Basics in DIWire.

Demonstrates how to use scopes with enter_scope() context manager.
Scopes allow grouping related service resolutions together.
"""

from enum import Enum

from diwire import Container


class Scope(str, Enum):
    """Application scope definitions."""

    REQUEST = "request"


class RequestContext:
    """Holds request-specific data."""

    def __init__(self) -> None:
        self.request_id = id(self)

    def __repr__(self) -> str:
        return f"RequestContext(request_id={self.request_id})"


def main() -> None:
    container = Container()
    container.register(RequestContext)

    # Using enter_scope() with an Enum value
    print("Scope usage with context manager:\n")

    with container.enter_scope(Scope.REQUEST) as scope:
        # Resolve services within the scope
        ctx1 = scope.resolve(RequestContext)
        ctx2 = scope.resolve(RequestContext)

        print(f"Inside scope '{Scope.REQUEST.value}':")
        print(f"  ctx1: {ctx1}")
        print(f"  ctx2: {ctx2}")
        print(f"  Same instance (transient): {ctx1 is ctx2}")

    # Each scope is independent
    print("\nMultiple independent scopes:")

    with container.enter_scope(Scope.REQUEST) as scope1:
        ctx_a = scope1.resolve(RequestContext)
        print(f"  Scope 1 context: {ctx_a}")

    with container.enter_scope(Scope.REQUEST) as scope2:
        ctx_b = scope2.resolve(RequestContext)
        print(f"  Scope 2 context: {ctx_b}")

    print(f"  Different instances: {ctx_a is not ctx_b}")


if __name__ == "__main__":
    main()
