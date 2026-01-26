"""Basic async factory example.

Demonstrates how to register and resolve services with async factories.
Async factories are auto-detected - no special configuration needed.
"""

import asyncio

from diwire import Container, Lifetime


# Simulated async database connection
class Database:
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.connected = False

    async def connect(self) -> None:
        # Simulate async connection
        await asyncio.sleep(0.01)
        self.connected = True

    async def query(self, sql: str) -> list[dict]:
        if not self.connected:
            raise RuntimeError("Not connected")
        await asyncio.sleep(0.01)
        return [{"id": 1, "name": "Example"}]


# Async factory function - automatically detected as async
async def create_database() -> Database:
    """Async factory that creates and connects a database."""
    db = Database("postgresql://localhost/mydb")
    await db.connect()
    return db


async def main() -> None:
    container = Container()

    # Register with async factory - is_async is auto-detected
    container.register(Database, factory=create_database, lifetime=Lifetime.SINGLETON)

    # Must use aresolve() for async dependencies
    db = await container.aresolve(Database)
    print(f"Database connected: {db.connected}")

    # Query the database
    results = await db.query("SELECT * FROM users")
    print(f"Query results: {results}")

    # Singleton behavior works the same - same instance returned
    db2 = await container.aresolve(Database)
    print(f"Same instance: {db is db2}")


if __name__ == "__main__":
    asyncio.run(main())
