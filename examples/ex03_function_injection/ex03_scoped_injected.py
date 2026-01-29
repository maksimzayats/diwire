"""ScopedInjected for Per-Call Scopes.

Demonstrates how resolve(func, scope=...) returns a ScopedInjected
that creates a new scope for each function call. This is useful for
request handlers where each call needs its own scope.
"""

import random
from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from diwire import Container, Injected, Lifetime


class Scope(str, Enum):
    """Application scope definitions."""

    REQUEST = "request"


@dataclass
class RequestSession:
    """Session shared within a single request."""

    session_id: int = 0

    def __post_init__(self) -> None:
        self.session_id = random.randint(1000, 9999)


@dataclass
class UserService:
    """Service that uses the request session."""

    session: RequestSession

    def get_user(self, user_id: int) -> str:
        return f"User {user_id} (session: {self.session.session_id})"


@dataclass
class AuditService:
    """Service that also uses the request session."""

    session: RequestSession

    def log_access(self, user_id: int) -> str:
        return f"Logged access for user {user_id} (session: {self.session.session_id})"


def handle_request(
    user_id: int,
    *,
    user_service: Annotated[UserService, Injected()],
    audit_service: Annotated[AuditService, Injected()],
) -> dict[str, str]:
    """Handle a request - both services should share the same session."""
    return {
        "user": user_service.get_user(user_id),
        "audit": audit_service.log_access(user_id),
    }


def main() -> None:
    container = Container()

    # RequestSession is SCOPED - shared within a scope
    container.register(
        RequestSession,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container.register(UserService)
    container.register(AuditService)

    # Resolve with scope parameter returns ScopedInjected
    handler = container.resolve(handle_request, scope=Scope.REQUEST)
    print(f"Handler type: {type(handler)}")

    print("\nEach call creates a new scope:")
    for i in range(1, 4):
        result = handler(user_id=i)
        print(f"\n  Request {i}:")
        print(f"    {result['user']}")
        print(f"    {result['audit']}")
        # Note: session IDs match within each request but differ across requests


if __name__ == "__main__":
    main()
