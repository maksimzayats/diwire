"""Generator factories with scope cleanup.

Demonstrates generator factory support:
- Yielded instance is used by the container
- Generator is closed on scope exit
"""

from __future__ import annotations

from collections.abc import Generator
from enum import Enum

from diwire import Container, Lifetime


class Scope(str, Enum):
    """Application scope definitions."""

    REQUEST = "request"


class Session:
    """A session that needs cleanup when the scope ends."""

    def __init__(self) -> None:
        self.session_id = id(self)
        self.closed = False

    def close(self) -> None:
        self.closed = True
        print(f"Session {self.session_id} closed")

    def __repr__(self) -> str:
        return f"Session(id={self.session_id}, closed={self.closed})"


def session_factory() -> Generator[Session, None, None]:
    session = Session()
    print(f"Session {session.session_id} opened")
    try:
        yield session
    finally:
        session.close()


def main() -> None:
    container = Container()
    container.register(
        Session,
        factory=session_factory,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    print("Generator factory scope behavior:\n")
    with container.enter_scope(Scope.REQUEST):
        session1 = container.resolve(Session)
        session2 = container.resolve(Session)
        print(f"session1: {session1}")
        print(f"session2: {session2}")
        print(f"Same instance: {session1 is session2}")

    print("\nScope exited; generator cleanup should have run.")


if __name__ == "__main__":
    main()
