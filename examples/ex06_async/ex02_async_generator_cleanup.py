"""Async generator factory with automatic cleanup.

Demonstrates how async generators can be used for resource lifecycle management.
The cleanup code in the finally block runs automatically when the scope exits.
"""

import asyncio

from diwire import Container, Lifetime


class DatabaseSession:
    """Represents a database session that needs cleanup."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.closed = False

    async def execute(self, query: str) -> list[dict]:
        if self.closed:
            raise RuntimeError("Session is closed")
        await asyncio.sleep(0.01)
        return [{"result": f"executed: {query}"}]

    async def close(self) -> None:
        print(f"  Closing session {self.session_id}")
        await asyncio.sleep(0.01)
        self.closed = True


# Async generator factory - cleanup runs in finally block
async def create_session():
    """Async generator factory with automatic cleanup.

    The code before yield creates the resource.
    The code in finally runs when the scope exits.
    """
    session = DatabaseSession("session-123")
    print(f"  Created session {session.session_id}")
    try:
        yield session
    finally:
        # This runs automatically when the scope exits
        await session.close()


async def main() -> None:
    container = Container()

    # Register async generator with scope
    container.register(
        DatabaseSession,
        factory=create_session,
        lifetime=Lifetime.SCOPED,
        scope="request",
    )

    print("Starting request scope...")

    # Use async context manager for proper cleanup
    async with container.enter_scope("request"):
        session = await container.aresolve(DatabaseSession)
        print(f"  Got session: {session.session_id}")

        # Use the session
        results = await session.execute("SELECT * FROM users")
        print(f"  Query results: {results}")

        # Same session within scope
        session2 = await container.aresolve(DatabaseSession)
        print(f"  Same session: {session is session2}")

    # Session is automatically closed when scope exits
    print("Request scope ended.")
    print(f"Session closed: {session.closed}")


if __name__ == "__main__":
    asyncio.run(main())
