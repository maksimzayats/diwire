"""Repository Pattern with Scoped Session.

Demonstrates a repository pattern where the database session
is shared within a scope, and repositories are transient.
"""

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated

from diwire import Container, Injected, Lifetime


class Scope(str, Enum):
    """Application scope definitions."""

    UNIT_OF_WORK = "unit_of_work"


@dataclass
class Session:
    """Database session - shared within a unit of work."""

    session_id: int = field(default_factory=lambda: random.randint(1000, 9999))
    _pending_changes: list[str] = field(default_factory=list)

    def add(self, entity: str) -> None:
        self._pending_changes.append(f"INSERT {entity}")
        print(f"    [Session {self.session_id}] Staged: INSERT {entity}")

    def update(self, entity: str) -> None:
        self._pending_changes.append(f"UPDATE {entity}")
        print(f"    [Session {self.session_id}] Staged: UPDATE {entity}")

    def commit(self) -> None:
        print(f"    [Session {self.session_id}] Committing {len(self._pending_changes)} changes")
        self._pending_changes.clear()

    def rollback(self) -> None:
        print(f"    [Session {self.session_id}] Rolling back")
        self._pending_changes.clear()


@dataclass
class UserRepository:
    """Repository for User entities."""

    session: Session

    def create(self, name: str) -> str:
        self.session.add(f"User(name={name})")
        return f"User({name})"

    def update_email(self, user_id: int, email: str) -> None:
        self.session.update(f"User(id={user_id}, email={email})")


@dataclass
class OrderRepository:
    """Repository for Order entities."""

    session: Session

    def create(self, user_id: int, product: str) -> str:
        self.session.add(f"Order(user={user_id}, product={product})")
        return f"Order({product})"


def create_user_with_order(
    user_repo: Annotated[UserRepository, Injected()],
    order_repo: Annotated[OrderRepository, Injected()],
    session: Annotated[Session, Injected()],
    username: str,
    product: str,
) -> dict[str, str]:
    """Create a user and their first order in a single unit of work."""
    user = user_repo.create(username)
    order = order_repo.create(user_id=1, product=product)
    session.commit()
    return {"user": user, "order": order}


def main() -> None:
    container = Container()

    # Session is SCOPED - same session for entire unit of work
    container.register(
        Session,
        lifetime=Lifetime.SCOPED,
        scope=Scope.UNIT_OF_WORK,
    )
    # Repositories are transient but share the scoped session
    container.register(UserRepository)
    container.register(OrderRepository)

    # Create handler with automatic scope per call
    handler = container.resolve(create_user_with_order, scope=Scope.UNIT_OF_WORK)

    print("Repository pattern with scoped session:\n")

    # Unit of work 1
    print("Unit of Work 1:")
    result1 = handler(username="alice", product="Laptop")
    print(f"  Result: {result1}\n")

    # Unit of work 2 (new session)
    print("Unit of Work 2:")
    result2 = handler(username="bob", product="Phone")
    print(f"  Result: {result2}\n")

    # Manual scope management example
    print("Manual scope management:")
    with container.enter_scope(Scope.UNIT_OF_WORK) as scope:
        user_repo = scope.resolve(UserRepository)
        order_repo = scope.resolve(OrderRepository)
        session = scope.resolve(Session)

        # Both repos share the same session
        print(f"  Session: {session}")
        print(f"  UserRepository session: {user_repo.session.session_id}")
        print(f"  OrderRepository session: {order_repo.session.session_id}")
        print(f"  Same session: {user_repo.session is order_repo.session}")


if __name__ == "__main__":
    main()
