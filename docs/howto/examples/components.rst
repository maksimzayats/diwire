.. meta::
   :description: diwire components examples: named components for multiple implementations using Component markers and ServiceKey.

Components
==========

Named components
----------------

Demonstrates how to register and resolve multiple implementations of the same
interface using ``Component`` markers and ``ServiceKey``.

Register and resolve by ServiceKey
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass
   from typing import Protocol

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


   def main() -> None:
       container = Container()

       # Register multiple implementations with different components.
       container.register(
           ServiceKey(value=Database, component=Component("primary")),
           instance=PostgresDatabase(host="primary.postgres.example.com"),
       )
       container.register(
           ServiceKey(value=Database, component=Component("replica")),
           instance=MySQLDatabase(host="replica.mysql.example.com"),
       )

       primary = container.resolve(ServiceKey(value=Database, component=Component("primary")))
       replica = container.resolve(ServiceKey(value=Database, component=Component("replica")))

       print(primary.query("SELECT 1"))
       print(replica.query("SELECT 1"))


   if __name__ == "__main__":
       main()

Inject named components via Annotated
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``Annotated[Database, Component("...")]`` to inject a specific implementation.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass
   from typing import Annotated, Protocol

   from diwire import Container
   from diwire.service_key import Component, ServiceKey


   class Database(Protocol):
       def query(self, sql: str) -> str: ...


   @dataclass
   class PostgresDatabase:
       host: str

       def query(self, sql: str) -> str:
           return f"[Postgres@{self.host}] {sql}"


   @dataclass
   class MySQLDatabase:
       host: str

       def query(self, sql: str) -> str:
           return f"[MySQL@{self.host}] {sql}"


   @dataclass
   class Repository:
       primary_db: Annotated[Database, Component("primary")]
       replica_db: Annotated[Database, Component("replica")]

       def read(self) -> str:
           return self.replica_db.query("SELECT 1")

       def write(self) -> str:
           return self.primary_db.query("INSERT ...")


   def main() -> None:
       container = Container()
       container.register(
           ServiceKey(value=Database, component=Component("primary")),
           instance=PostgresDatabase(host="primary.postgres.example.com"),
       )
       container.register(
           ServiceKey(value=Database, component=Component("replica")),
           instance=MySQLDatabase(host="replica.mysql.example.com"),
       )
       container.register(Repository)

       repo = container.resolve(Repository)
       print(repo.write())
       print(repo.read())


   if __name__ == "__main__":
       main()

Read more
---------

- :doc:`../../core/components`
- :doc:`../../core/registration`
