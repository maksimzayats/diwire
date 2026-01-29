"""Scope Mismatch Detection.

Demonstrates DIWireScopeMismatchError when trying to resolve from an exited scope.
"""

from enum import Enum

from diwire import Container, Lifetime
from diwire.exceptions import DIWireScopeMismatchError


class Scope(str, Enum):
    """Application scope definitions."""

    REQUEST = "request"


class RequestSession:
    """Session that must be resolved within a REQUEST scope."""


def main() -> None:
    container = Container()

    # Register session as SCOPED for REQUEST scope
    container.register(
        RequestSession,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    # Trying to use a scope after it has exited
    print("Scenario: Using a scope reference after it has exited\n")

    scope_ref = None
    with container.enter_scope(Scope.REQUEST) as scope:
        # Save reference to scope
        scope_ref = scope
        session = scope.resolve(RequestSession)
        print(f"Inside scope: resolved {session}")

    # Now scope has exited but we try to use the saved reference
    print("\nAttempting to resolve from exited scope:")
    try:
        scope_ref.resolve(RequestSession)
    except DIWireScopeMismatchError as e:
        print("  DIWireScopeMismatchError caught!")
        print(f"    Service: {e.service_key}")
        print(f"    Registered scope: {e.registered_scope}")
        print(f"    Current scope: {e.current_scope}")

    # Correct usage - always use scopes within their context manager
    print("\nCorrect usage - resolve within active scope context:")
    with container.enter_scope(Scope.REQUEST) as scope:
        session = scope.resolve(RequestSession)
        print(f"  Successfully resolved: {session}")


if __name__ == "__main__":
    main()
