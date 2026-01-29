"""HTTP Request Handler Pattern.

Demonstrates a real-world pattern for handling HTTP requests where
each request gets its own scope with shared services.
"""

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated

from diwire import Container, Injected, Lifetime


class Scope(str, Enum):
    """Application scope definitions."""

    REQUEST = "request"


@dataclass
class RequestContext:
    """Context shared across all services within a single request."""

    request_id: str = field(default_factory=lambda: f"req-{random.randint(1000, 9999)}")
    user_id: int | None = None
    authenticated: bool = False


@dataclass
class AuthService:
    """Handles authentication within the request context."""

    ctx: RequestContext

    def authenticate(self, token: str) -> bool:
        # Simulate authentication
        if token.startswith("valid-"):
            self.ctx.authenticated = True
            self.ctx.user_id = int(token.split("-")[1])
            return True
        return False


@dataclass
class UserService:
    """User operations using request context."""

    ctx: RequestContext

    def get_current_user(self) -> dict[str, str | int | None]:
        if not self.ctx.authenticated:
            return {"error": "Not authenticated"}
        return {
            "user_id": self.ctx.user_id,
            "request_id": self.ctx.request_id,
        }


@dataclass
class AuditLogger:
    """Logs actions with request context."""

    ctx: RequestContext

    def log(self, action: str) -> str:
        return f"[{self.ctx.request_id}] user={self.ctx.user_id}: {action}"


def handle_get_user(
    auth: Annotated[AuthService, Injected()],
    user_service: Annotated[UserService, Injected()],
    audit: Annotated[AuditLogger, Injected()],
    token: str,
) -> dict[str, str | int | None]:
    """Handle GET /user request."""
    auth.authenticate(token)
    user = user_service.get_current_user()
    print(f"  {audit.log('get_user')}")
    return user


def main() -> None:
    container = Container()

    # RequestContext is shared within each request
    container.register(
        RequestContext,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    # Services are transient but receive the scoped RequestContext
    container.register(AuthService)
    container.register(UserService)
    container.register(AuditLogger)

    # Create a scoped handler - each call gets its own scope
    handler = container.resolve(handle_get_user, scope=Scope.REQUEST)

    print("Simulating HTTP requests:\n")

    # Request 1
    print("Request 1 (valid token):")
    result1 = handler(token="valid-42")
    print(f"  Response: {result1}\n")

    # Request 2 (different scope, different context)
    print("Request 2 (invalid token):")
    result2 = handler(token="invalid")
    print(f"  Response: {result2}\n")

    # Request 3
    print("Request 3 (valid token, different user):")
    result3 = handler(token="valid-99")
    print(f"  Response: {result3}")


if __name__ == "__main__":
    main()
