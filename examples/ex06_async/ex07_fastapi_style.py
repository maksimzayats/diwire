"""FastAPI-style web application pattern.

Demonstrates a realistic usage pattern similar to how you'd use
async DI in a FastAPI or similar async web framework.
"""

import asyncio
from dataclasses import dataclass
from typing import Annotated

from diwire import Container, Injected, Lifetime

# =============================================================================
# Domain Models
# =============================================================================


@dataclass
class User:
    id: int
    email: str
    name: str


@dataclass
class Order:
    id: int
    user_id: int
    total: float
    status: str


# =============================================================================
# Repository Layer (async database access)
# =============================================================================


class UserRepository:
    """Simulated async user repository."""

    _users = {
        1: User(1, "alice@example.com", "Alice"),
        2: User(2, "bob@example.com", "Bob"),
    }

    async def get_by_id(self, user_id: int) -> User | None:
        await asyncio.sleep(0.01)  # Simulate DB query
        return self._users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        await asyncio.sleep(0.01)
        for user in self._users.values():
            if user.email == email:
                return user
        return None


class OrderRepository:
    """Simulated async order repository."""

    _orders = {
        1: Order(1, 1, 99.99, "completed"),
        2: Order(2, 1, 149.50, "pending"),
        3: Order(3, 2, 75.00, "completed"),
    }

    async def get_by_user(self, user_id: int) -> list[Order]:
        await asyncio.sleep(0.01)
        return [o for o in self._orders.values() if o.user_id == user_id]


# =============================================================================
# Service Layer
# =============================================================================


class UserService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def get_user(self, user_id: int) -> User | None:
        return await self.user_repo.get_by_id(user_id)


class OrderService:
    def __init__(self, order_repo: OrderRepository, user_repo: UserRepository):
        self.order_repo = order_repo
        self.user_repo = user_repo

    async def get_user_orders(self, user_id: int) -> dict:
        # Parallel fetch of user and orders
        user_task = self.user_repo.get_by_id(user_id)
        orders_task = self.order_repo.get_by_user(user_id)

        user, orders = await asyncio.gather(user_task, orders_task)

        if user is None:
            return {"error": "User not found"}

        return {
            "user": {"id": user.id, "name": user.name, "email": user.email},
            "orders": [{"id": o.id, "total": o.total, "status": o.status} for o in orders],
            "total_spent": sum(o.total for o in orders if o.status == "completed"),
        }


# =============================================================================
# Database Session (scoped, with cleanup)
# =============================================================================


class DatabaseSession:
    """Per-request database session with transaction support."""

    _counter = 0

    def __init__(self):
        DatabaseSession._counter += 1
        self.session_id = DatabaseSession._counter
        self.in_transaction = False

    async def begin(self) -> None:
        self.in_transaction = True

    async def commit(self) -> None:
        await asyncio.sleep(0.005)
        self.in_transaction = False

    async def rollback(self) -> None:
        await asyncio.sleep(0.005)
        self.in_transaction = False

    async def close(self) -> None:
        if self.in_transaction:
            await self.rollback()


async def create_db_session():
    """Async generator factory for database session."""
    session = DatabaseSession()
    await session.begin()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# =============================================================================
# Request Handlers (with Injected injection)
# =============================================================================


async def get_user_handler(
    user_service: Annotated[UserService, Injected()],
    session: Annotated[DatabaseSession, Injected()],
    user_id: int,
) -> dict:
    """Handler to get a single user."""
    print(f"  [Session {session.session_id}] Getting user {user_id}")
    user = await user_service.get_user(user_id)
    if user is None:
        return {"error": "User not found"}
    return {"id": user.id, "name": user.name, "email": user.email}


async def get_user_orders_handler(
    order_service: Annotated[OrderService, Injected()],
    session: Annotated[DatabaseSession, Injected()],
    user_id: int,
) -> dict:
    """Handler to get user with their orders."""
    print(f"  [Session {session.session_id}] Getting orders for user {user_id}")
    return await order_service.get_user_orders(user_id)


# =============================================================================
# Application Setup
# =============================================================================


def create_container() -> Container:
    """Configure the DI container for the application."""
    container = Container()

    # Repositories - singleton (shared connection pool in real app)
    container.register(UserRepository, lifetime=Lifetime.SINGLETON)
    container.register(OrderRepository, lifetime=Lifetime.SINGLETON)

    # Services - singleton (stateless)
    container.register(UserService, lifetime=Lifetime.SINGLETON)
    container.register(OrderService, lifetime=Lifetime.SINGLETON)

    # Database session - scoped per request with cleanup
    container.register(
        DatabaseSession,
        factory=create_db_session,
        lifetime=Lifetime.SCOPED,
        scope="request",
    )

    return container


# =============================================================================
# Simulated Request Handling
# =============================================================================


async def handle_request(container: Container, handler, **kwargs) -> dict:
    """Simulate handling an HTTP request."""
    # Each request gets its own scope
    async with container.enter_scope("request"):
        # Resolve the handler (gets AsyncScopedInjected due to scoped deps)
        injected_handler = await container.aresolve(handler)
        return await injected_handler(**kwargs)


async def main() -> None:
    container = create_container()

    print("=== FastAPI-Style Async DI Demo ===\n")

    # Simulate concurrent requests
    print("Processing concurrent requests...\n")

    results = await asyncio.gather(
        handle_request(container, get_user_handler, user_id=1),
        handle_request(container, get_user_orders_handler, user_id=1),
        handle_request(container, get_user_handler, user_id=2),
        handle_request(container, get_user_orders_handler, user_id=2),
        handle_request(container, get_user_handler, user_id=999),  # Not found
    )

    print("\n--- Results ---")
    for i, result in enumerate(results, 1):
        print(f"Request {i}: {result}")


if __name__ == "__main__":
    asyncio.run(main())
