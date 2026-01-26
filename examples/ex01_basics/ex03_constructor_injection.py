"""Constructor Injection in DIWire.

Demonstrates automatic dependency resolution through constructor parameters.
The container analyzes type hints and injects dependencies automatically.
"""

from dataclasses import dataclass
from typing import Any

from diwire import Container


@dataclass
class Config:
    """Application configuration."""

    database_url: str = "postgresql://localhost/app"
    debug: bool = True


@dataclass
class Database:
    """Database connection that depends on Config."""

    config: Config

    def query(self, sql: str, **kwargs: Any) -> str:
        return f"Executing on {self.config.database_url}: {sql.format(**kwargs)}"


@dataclass
class UserRepository:
    """Repository that depends on Database."""

    db: Database

    def find_user(self, user_id: int) -> str:
        return self.db.query("SELECT * FROM users WHERE id = {user_id}", user_id=user_id)


@dataclass
class UserService:
    """Service that depends on UserRepository."""

    repo: UserRepository

    def get_user_info(self, user_id: int) -> str:
        return f"User info: {self.repo.find_user(user_id)}"


def main() -> None:
    container = Container()

    # Register Config with a specific instance
    container.register(Config, instance=Config(database_url="postgresql://prod/app"))

    # Resolve UserService - container automatically resolves entire chain:
    # UserService -> UserRepository -> Database -> Config
    service = container.resolve(UserService)

    result = service.get_user_info(42)
    print(result)

    # The entire dependency chain was resolved:
    print("\nDependency chain resolved:")
    print(f"  UserService has repo: {service.repo}")
    print(f"  UserRepository has db: {service.repo.db}")
    print(f"  Database has config: {service.repo.db.config}")


if __name__ == "__main__":
    main()
