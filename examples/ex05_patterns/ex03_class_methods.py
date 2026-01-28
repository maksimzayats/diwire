"""Class Method Decoration Pattern.

Demonstrates using container_context.resolve() decorator on class methods.
This pattern is useful for controller/handler classes where you want
dependency injection on instance methods.
"""

from dataclasses import dataclass, field
from typing import Annotated

from diwire import Container, Injected, Lifetime, container_context


@dataclass
class Database:
    """Simulated database connection."""

    connection_id: str = field(default_factory=lambda: "db-001")

    def query(self, _sql: str) -> list[dict[str, str]]:
        # Simulated query - returns mock data
        return [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}]


@dataclass
class Logger:
    """Simple logger service."""

    def info(self, message: str) -> None:
        print(f"[INFO] {message}")


@dataclass
class Cache:
    """Simple cache service."""

    _data: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def get(self, key: str) -> list[dict[str, str]] | None:
        return self._data.get(key)

    def set(self, key: str, value: list[dict[str, str]]) -> None:
        self._data[key] = value


class UserController:
    """Controller class with decorated instance methods.

    Each method uses container_context.resolve() to inject dependencies.
    The decorator properly binds 'self' so methods work as expected.
    """

    def __init__(self, prefix: str = "/api") -> None:
        self.prefix = prefix

    @container_context.resolve()
    def list_users(
        self,
        db: Annotated[Database, Injected()],
        logger: Annotated[Logger, Injected()],
    ) -> list[dict[str, str]]:
        """List all users - instance method with injected dependencies."""
        logger.info(f"{self.prefix}/users - Fetching all users")  # noqa: G004
        return db.query("SELECT * FROM users")

    @container_context.resolve()
    def get_user_cached(
        self,
        user_id: str,
        db: Annotated[Database, Injected()],
        cache: Annotated[Cache, Injected()],
        logger: Annotated[Logger, Injected()],
    ) -> dict[str, str] | None:
        """Get user with caching - shows mixing caller args with injected deps."""
        cache_key = f"user:{user_id}"

        cached = cache.get(cache_key)
        if cached:
            logger.info(f"{self.prefix}/users/{user_id} - Cache hit")  # noqa: G004
            return cached[0] if cached else None

        logger.info(f"{self.prefix}/users/{user_id} - Cache miss, querying DB")  # noqa: G004
        users = db.query(f"SELECT * FROM users WHERE id = {user_id}")
        if users:
            cache.set(cache_key, users)
            return users[0]
        return None


def main() -> None:
    # Set up container
    container = Container()
    container.register(Database, lifetime=Lifetime.SINGLETON)
    container.register(Logger, lifetime=Lifetime.SINGLETON)
    container.register(Cache, lifetime=Lifetime.SINGLETON)

    # Set container in context
    token = container_context.set_current(container)

    try:
        # Create controller instance
        controller = UserController(prefix="/v1/api")

        print("=== Instance Method Decoration Example ===\n")

        # Call decorated instance method - 'self' is properly bound
        print("1. Calling list_users():")
        users = controller.list_users()
        print(f"   Result: {users}\n")

        # Call with caller-provided argument + injected dependencies
        print("2. Calling get_user_cached('1') - first call (cache miss):")
        user = controller.get_user_cached("1")
        print(f"   Result: {user}\n")

        print("3. Calling get_user_cached('1') - second call (cache hit):")
        user = controller.get_user_cached("1")
        print(f"   Result: {user}\n")

        # Demonstrate self.prefix is accessible
        print("4. Controller prefix is accessible in methods:")
        print(f"   controller.prefix = '{controller.prefix}'")

    finally:
        container_context.reset(token)


if __name__ == "__main__":
    main()
