"""Named Components for Multiple Implementations.

Demonstrates how to register and resolve multiple implementations
of the same interface using Component markers and ServiceKey.
"""

from dataclasses import dataclass
from typing import Annotated, Protocol

from diwire import Container
from diwire.service_key import Component, ServiceKey


class Database(Protocol):
    """Database interface."""

    def query(self, sql: str) -> str: ...


@dataclass
class PostgresDatabase:
    """PostgreSQL implementation."""

    host: str = "postgres.example.com"

    def query(self, sql: str) -> str:
        return f"[Postgres@{self.host}] {sql}"


@dataclass
class MySQLDatabase:
    """MySQL implementation."""

    host: str = "mysql.example.com"

    def query(self, sql: str) -> str:
        return f"[MySQL@{self.host}] {sql}"


@dataclass
class Repository:
    """Repository that uses a specific database component."""

    # Use Annotated with Component to inject a specific implementation
    primary_db: Annotated[Database, Component("primary")]
    replica_db: Annotated[Database, Component("replica")]

    def read(self, sql: str) -> str:
        return self.replica_db.query(sql)

    def write(self, sql: str) -> str:
        return self.primary_db.query(sql)


def main() -> None:
    container = Container()

    # Register multiple implementations with different components
    container.register(
        ServiceKey(value=Database, component=Component("primary")),
        instance=PostgresDatabase(host="primary.postgres.example.com"),
    )
    container.register(
        ServiceKey(value=Database, component=Component("replica")),
        instance=MySQLDatabase(host="replica.mysql.example.com"),
    )
    container.register(Repository)

    # Resolve by ServiceKey
    primary = container.resolve(ServiceKey(value=Database, component=Component("primary")))
    replica = container.resolve(ServiceKey(value=Database, component=Component("replica")))

    print("Direct resolution by ServiceKey:")
    print(f"  Primary: {primary.query('SELECT 1')}")
    print(f"  Replica: {replica.query('SELECT 1')}")

    # Resolve by Annotated type
    primary_annotated: Database = container.resolve(Annotated[Database, Component("primary")])
    print("\nResolution by Annotated type:")
    print(f"  Primary: {primary_annotated.query('SELECT 1')}")

    # Repository gets both databases injected
    repo = container.resolve(Repository)
    print("\nRepository with injected components:")
    print(f"  Write: {repo.write('INSERT INTO users ...')}")
    print(f"  Read: {repo.read('SELECT * FROM users')}")


if __name__ == "__main__":
    main()
