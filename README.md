# diwire

**Type-driven dependency injection for Python. Zero dependencies. Zero boilerplate.**

[![PyPI version](https://img.shields.io/pypi/v/diwire.svg)](https://pypi.org/project/diwire/)
[![Python versions](https://img.shields.io/pypi/pyversions/diwire.svg)](https://pypi.org/project/diwire/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![codecov](https://codecov.io/gh/MaksimZayats/diwire/graph/badge.svg)](https://codecov.io/gh/MaksimZayats/diwire)

diwire is a dependency injection container for Python 3.10+ that builds your object graph from type hints alone. It
supports scoped lifetimes, async-first resolution, generator-based cleanup,
open generics, and free-threaded Python (no-GIL) — all with zero runtime dependencies.

## Quick Start

Define your classes. Resolve the top-level one. diwire figures out the rest.

```python
from dataclasses import dataclass
from diwire import Container, Lifetime


@dataclass
class Database:
    host: str = "localhost"


@dataclass
class UserRepository:
    db: Database


@dataclass
class UserService:
    repo: UserRepository


container = Container(autoregister_default_lifetime=Lifetime.TRANSIENT)
service = container.resolve(UserService)

print(service.repo.db.host)  # => localhost
```

No registration calls. No configuration. diwire reads the type hints on `UserService`, sees it needs a `UserRepository`,
which needs a `Database`, and builds the entire chain automatically.

## Installation

```bash
uv add diwire
```

```bash
pip install diwire
```

## Features

### Auto-Wiring

Dependencies are resolved from type hints — no manual wiring required.

```python
from dataclasses import dataclass
from diwire import Container


@dataclass
class Logger:
    level: str = "INFO"


@dataclass
class AuthService:
    logger: Logger


@dataclass
class App:
    auth: AuthService
    logger: Logger


container = Container()
app = container.resolve(App)

print(app.auth.logger.level)  # => INFO
print(app.logger.level)  # => INFO
```

### Decorator Registration

Use `@container.register` as a decorator on classes, factory functions, and static methods — with or without parameters.

```python
from dataclasses import dataclass
from typing import Annotated, Protocol

from diwire import Container, Lifetime, Component


class IDatabase(Protocol):
    def query(self, sql: str) -> str: ...


container = Container()


# Bare decorator — registers the class with default lifetime
@container.register
class Config:
    debug: bool = True


# With lifetime parameter
@container.register(lifetime=Lifetime.SINGLETON)
class Logger:
    def log(self, msg: str) -> None:
        print(f"[LOG] {msg}")


# Interface binding via decorator
@container.register(IDatabase, lifetime=Lifetime.SINGLETON)
class PostgresDatabase:
    def query(self, sql: str) -> str:
        return f"result of: {sql}"


# Factory function — return type is inferred from annotation
@container.register
def create_connection_string(config: Config) -> Annotated[str, Component("connection_string")]:
    return f"postgres://localhost?debug={config.debug}"


print(container.resolve(Config).debug)  # => True
print(container.resolve(IDatabase).query("SELECT 1"))  # => result of: SELECT 1
print(container.resolve(Annotated[str, Component("connection_string")]))  # => postgres://localhost?debug=True
```

### Lifetimes

Control how instances are created and shared.

| Lifetime    | Behavior                                         |
|-------------|--------------------------------------------------|
| `TRANSIENT` | New instance every time                          |
| `SINGLETON` | One shared instance for the container's lifetime |
| `SCOPED`    | One instance per scope (e.g. per request)        |

```python
from dataclasses import dataclass
from diwire import Container, Lifetime


@dataclass
class Config:
    debug: bool = True


container = Container()
container.register(Config, lifetime=Lifetime.SINGLETON)

a = container.resolve(Config)
b = container.resolve(Config)
print(a is b)  # => True

container.register(Config, lifetime=Lifetime.TRANSIENT)
c = container.resolve(Config)
print(a is c)  # => False
```

### Scopes & Cleanup

Scopes manage per-request lifetimes. Generator factories clean up automatically when the scope exits.

```python
from collections.abc import Generator
from diwire import Container, Lifetime


class DBSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def session_factory() -> Generator[DBSession, None, None]:
    session = DBSession()
    try:
        yield session
    finally:
        session.close()  # runs automatically on scope exit


container = Container()
container.register(DBSession, factory=session_factory, lifetime=Lifetime.SCOPED, scope="request")

with container.enter_scope("request") as scope:
    session = scope.resolve(DBSession)
    print(session.closed)  # => False

print(session.closed)  # => True
```

### Auto-Register Safety

When auto-registration is enabled and a type already has a scoped registration, diwire raises
`DIWireScopeMismatchError` instead of silently creating a second, unscoped instance. This prevents bugs where you
expect a scoped service but accidentally resolve it outside the correct scope.

```python
from dataclasses import dataclass

from diwire import Container, Lifetime


@dataclass
class Session:
    active: bool = True


container = Container(autoregister=True)
container.register(Session, lifetime=Lifetime.SCOPED, scope="request")

# Resolving outside any scope raises — no silent fallback
# container.resolve(Session)  # => DIWireScopeMismatchError

# Resolving inside the correct scope works
with container.enter_scope("request") as scope:
    session = scope.resolve(Session)
    print(session.active)  # => True

# Unregistered types still auto-register normally
@dataclass
class Logger:
    level: str = "INFO"

print(container.resolve(Logger).level)  # => INFO
```

### Async Support

`aresolve()` works with async factories and async generators. Independent dependencies are resolved in parallel via
`asyncio.gather()`.

```python
import asyncio
from collections.abc import AsyncGenerator

from diwire import Container, Lifetime


class AsyncClient:
    def __init__(self) -> None:
        self.connected: bool = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.connected = False


async def client_factory() -> AsyncGenerator[AsyncClient, None]:
    client = AsyncClient()
    await client.connect()
    try:
        yield client
    finally:
        await client.close()


async def main() -> None:
    container = Container()
    container.register(
        AsyncClient,
        factory=client_factory,
        lifetime=Lifetime.SCOPED,
        scope="request",
    )

    async with container.enter_scope("request") as scope:
        client = await scope.aresolve(AsyncClient)
        print(client.connected)  # => True

    print(client.connected)  # => False


asyncio.run(main())
```

### Function Injection

Mark parameters with `Injected()` to inject dependencies while keeping other parameters caller-provided.

```python
from dataclasses import dataclass
from typing import Annotated
from diwire import Container, Injected


@dataclass
class EmailService:
    smtp_host: str = "smtp.example.com"

    def send(self, to: str, subject: str) -> str:
        return f"Sent '{subject}' to {to} via {self.smtp_host}"


def send_email(
    to: str,
    *,
    mailer: Annotated[EmailService, Injected()],
) -> str:
    return mailer.send(to=to, subject="Hello!")


container = Container()
send = container.resolve(send_email)
print(send(to="user@example.com"))  # => Sent 'Hello!' to user@example.com via smtp.example.com
```

### Interface Binding

Register a protocol or abstract base class and resolve it to a concrete implementation.

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from diwire import Container, Lifetime


class Clock(Protocol):
    def now(self) -> str: ...


@dataclass
class SystemClock:
    def now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")


container = Container()
container.register(Clock, concrete_class=SystemClock, lifetime=Lifetime.SINGLETON)

clock = container.resolve(Clock)
print(type(clock).__name__)  # => SystemClock
```

### Named Components

Use `Component` to register multiple implementations of the same interface.

```python
from dataclasses import dataclass
from typing import Annotated, Protocol
from diwire import Container, Component


class Cache(Protocol):
    def get(self, key: str) -> str: ...


@dataclass
class RedisCache:
    def get(self, key: str) -> str:
        return f"redis:{key}"


@dataclass
class MemoryCache:
    def get(self, key: str) -> str:
        return f"memory:{key}"


container = Container()
container.register(Annotated[Cache, Component("primary")], instance=RedisCache())
container.register(Annotated[Cache, Component("fallback")], instance=MemoryCache())

primary: Cache = container.resolve(Annotated[Cache, Component("primary")])
fallback: Cache = container.resolve(Annotated[Cache, Component("fallback")])

print(primary.get("user:1"))  # => redis:user:1
print(fallback.get("user:1"))  # => memory:user:1
```

### Open Generics

Register open generic factories and resolve closed generics with type-safe validation. TypeVar bounds and constraints
are enforced at resolution time.

```python
from dataclasses import dataclass
from typing import Generic, TypeVar
from diwire import Container


class Model:
    pass


T = TypeVar("T")
M = TypeVar("M", bound=Model)


@dataclass
class AnyBox(Generic[T]):
    value: str


@dataclass
class ModelBox(Generic[M]):
    model: M


container = Container()


@container.register(AnyBox[T])
def create_any_box(type_arg: type[T]) -> AnyBox[T]:
    return AnyBox(value=type_arg.__name__)


@container.register(ModelBox[M])
def create_model_box(model_cls: type[M]) -> ModelBox[M]:
    return ModelBox(model=model_cls())


print(container.resolve(AnyBox[int]))  # => AnyBox(value='int')
print(container.resolve(ModelBox[Model]))  # => ModelBox(model=<Model ...>)
```

### Global Context

`container_context` provides a context-local global container for app-wide lazy resolution.

```python
from dataclasses import dataclass
from typing import Annotated
from diwire import Container, Injected, container_context


@container_context.register()
@dataclass
class Service:
    name: str = "diwire"


@container_context.resolve()
def greet(service: Annotated[Service, Injected()]) -> str:
    return f"hello {service.name}"


container = Container()
container_context.set_current(container)

print(greet())  # => hello diwire
```

### Compilation

`compile()` precomputes the dependency graph into specialized providers, eliminating runtime reflection and dict
lookups. The container auto-compiles on first resolve by default.

```python
from dataclasses import dataclass
from diwire import Container, Lifetime


@dataclass
class ServiceA:
    pass


@dataclass
class ServiceB:
    a: ServiceA


container = Container()
container.register(ServiceA, lifetime=Lifetime.SINGLETON)
container.register(ServiceB, lifetime=Lifetime.TRANSIENT)

container.compile()  # pre-resolve the dependency graph

b = container.resolve(ServiceB)  # no reflection at resolve time
```

Set `auto_compile=False` on the container to control compilation timing manually.

## Tested Integrations

diwire works out of the box with classes that use generated `__init__` methods:

- **dataclasses** — standard library
- **[pydantic](https://docs.pydantic.dev/)** — `BaseModel` and `@pydantic.dataclasses.dataclass`
- **[attrs](https://www.attrs.org/)** — `@attrs.define`
- **[msgspec](https://jcristharif.com/msgspec/)** — `msgspec.Struct`

No adapters or plugins needed — diwire extracts dependencies from type hints automatically.

## API Reference

| Symbol              | Description                                                                                                                  |
|---------------------|------------------------------------------------------------------------------------------------------------------------------|
| `Container`         | DI container — `register`, `resolve`, `aresolve`, `enter_scope`, `close_scope`, `aclose_scope`, `compile`, `close`, `aclose` |
| `Lifetime`          | `TRANSIENT`, `SINGLETON`, `SCOPED`                                                                                           |
| `Injected`          | Parameter marker — `Annotated[T, Injected()]`                                                                                |
| `Component`         | Named component key — `Annotated[T, Component("name")]`                                                                      |
| `container_context` | Context-local global container — `set_current`, `register`, `resolve`                                                        |
| `ScopedContainer`   | Scoped container returned by `enter_scope()`                                                                                 |

## Examples & Documentation

See [`examples/README.md`](examples/README.md) for a guided tour of patterns, async usage, FastAPI integration, and
error handling.

## Contributing

Contributions are welcome. Please open an issue or pull request on [GitHub](https://github.com/maksimzayats/diwire).

## License

MIT
