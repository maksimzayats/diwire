"""Quickstart: automatic dependency wiring from type hints.

Start with plain classes, resolve only the top-level service, and see how
diwire builds the full dependency chain for you.
"""

from __future__ import annotations

from diwire import Container


class Database:
    def __init__(self) -> None:
        self.host = "localhost"


class UserRepository:
    def __init__(self, database: Database) -> None:
        self.database = database


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository


def main() -> None:
    container = Container()
    service = container.resolve(UserService)

    print(f"db_host={service.repository.database.host}")  # => db_host=localhost

    chain = (
        f"{type(service).__name__}"
        f">{type(service.repository).__name__}"
        f">{type(service.repository.database).__name__}"
    )
    print(f"chain={chain}")  # => chain=UserService>UserRepository>Database


if __name__ == "__main__":
    main()
