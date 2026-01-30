"""Registration Methods in DIWire.

Demonstrates three ways to register services:
1. Class registration - container creates instances
2. Factory registration - custom function creates instances
3. Instance registration - pre-created singleton
"""

from dataclasses import dataclass

from diwire import Container


@dataclass
class Database:
    host: str
    port: int


class Logger:
    def log(self, message: str) -> None:
        print(f"[LOG] {message}")


class Cache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}


def main() -> None:
    container = Container(autoregister=False)

    # 1. Simple class registration
    # Container will create instances using the class constructor
    container.register(Logger)
    logger = container.resolve(Logger)
    logger.log("Hello from registered class!")

    # 2. Factory registration
    # Use a factory function when you need custom instantiation logic
    def create_database() -> Database:
        return Database(host="localhost", port=5432)

    container.register(Database, factory=create_database)
    db = container.resolve(Database)
    print(f"Database: {db.host}:{db.port}")

    # 3. Instance registration
    # Register a pre-created object (always a singleton)
    cache_instance = Cache()
    cache_instance.data["key"] = "value"
    container.register(Cache, instance=cache_instance)

    resolved_cache = container.resolve(Cache)
    print(f"Cache data: {resolved_cache.data}")
    print(f"Same instance: {resolved_cache is cache_instance}")


if __name__ == "__main__":
    main()
