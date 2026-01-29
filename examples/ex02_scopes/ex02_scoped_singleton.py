"""Scoped Lifetime in DIWire.

Demonstrates SCOPED:
- Same instance within a scope
- Different instance across scopes
"""

from enum import Enum

from diwire import Container, Lifetime


class Scope(str, Enum):
    """Application scope definitions."""

    REQUEST = "request"


class Session:
    """A session that should be shared within a request scope."""

    def __init__(self) -> None:
        self.session_id = id(self)

    def __repr__(self) -> str:
        return f"Session(id={self.session_id})"


class Repository:
    """Repository that uses the current session."""

    def __init__(self, session: Session) -> None:
        self.session = session


def main() -> None:
    container = Container()

    # Register Session as SCOPED for REQUEST scope
    container.register(
        Session,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container.register(Repository)

    print("SCOPED behavior:\n")

    # Within the same scope, Session is shared
    with container.enter_scope(Scope.REQUEST) as scope:
        session1 = scope.resolve(Session)
        session2 = scope.resolve(Session)
        repo = scope.resolve(Repository)

        print("Request Scope 1:")
        print(f"  session1: {session1}")
        print(f"  session2: {session2}")
        print(f"  repo.session: {repo.session}")
        print(f"  All same instance: {session1 is session2 is repo.session}")

    # Different scope = different Session instance
    with container.enter_scope(Scope.REQUEST) as scope:
        session3 = scope.resolve(Session)
        repo2 = scope.resolve(Repository)

        print("\nRequest Scope 2:")
        print(f"  session3: {session3}")
        print(f"  repo2.session: {repo2.session}")
        print(f"  Same within scope: {session3 is repo2.session}")
        print(f"  Different from scope 1: {session3 is not session1}")


if __name__ == "__main__":
    main()
