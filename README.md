# diwire - dependency injection for Python

**Type-safe dependency injection with automatic wiring, scoped lifetimes, and async-safe factories.**

[![PyPI version](https://img.shields.io/pypi/v/diwire.svg)](https://pypi.org/project/diwire/)
[![Python versions](https://img.shields.io/pypi/pyversions/diwire.svg)](https://pypi.org/project/diwire/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![codecov](https://codecov.io/gh/MaksimZayats/diwire/graph/badge.svg)](https://codecov.io/gh/MaksimZayats/diwire)

`diwire` is a lightweight DI container for Python 3.10+ that resolves dependency graphs from type hints, supports scoped lifetimes, and cleans up resources via generator factories. It is async-first, thread-safe, and has zero runtime dependencies.

## Why diwire

- **Automatic wiring** from type hints (constructor and function injection)
- **Scoped lifetimes** for request/session workflows
- **Generator factories** with cleanup on scope exit
- **Async support** with `aresolve()` and async factories
- **Interface + component registration** for multiple implementations
- **Zero dependencies** and minimal overhead

## Installation

```bash
uv add diwire
```

```bash
pip install diwire
```

## Quick start

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

print(service.repo.db.host)
```

## Registering services

You can register classes, factories, or instances. `provides` lets you register by interface or abstract base class.

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
container.register(SystemClock, provides=Clock, lifetime=Lifetime.SINGLETON)
clock = container.resolve(Clock)
```

## Function injection

Mark parameters with `FromDI()` to inject dependencies while keeping other parameters caller-provided.

```python
from dataclasses import dataclass
from typing import Annotated

from diwire import Container, FromDI


@dataclass
class EmailService:
    smtp_host: str = "smtp.example.com"

    def send(self, to: str, subject: str) -> str:
        return f"Sent '{subject}' to {to} via {self.smtp_host}"


def send_email(
    to: str,
    *,
    mailer: Annotated[EmailService, FromDI()],
) -> str:
    return mailer.send(to, "Hello!")


container = Container()
send = container.resolve(send_email)
print(send(to="user@example.com"))
```

## Scopes and cleanup

Use scopes to manage request/session lifetimes. Generator factories clean up automatically.

```python
from collections.abc import Generator

from diwire import Container, Lifetime


class Session:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def session_factory() -> Generator[Session, None, None]:
    session = Session()
    try:
        yield session
    finally:
        session.close()


container = Container()
container.register(Session, factory=session_factory, lifetime=Lifetime.SCOPED_SINGLETON, scope="request")

with container.start_scope("request") as scope:
    session = scope.resolve(Session)
    assert session.closed is False
```

## Named components

Use `Component` and `ServiceKey` to register multiple implementations of the same interface.

```python
from dataclasses import dataclass
from typing import Annotated, Protocol

from diwire import Container
from diwire.service_key import Component


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
```

## Async support

Use `aresolve()` with async factories and async generator cleanup.

```python
import asyncio
from collections.abc import AsyncGenerator

from diwire import Container, Lifetime


class AsyncClient:
    async def close(self) -> None: ...


async def client_factory() -> AsyncGenerator[AsyncClient, None]:
    client = AsyncClient()
    try:
        yield client
    finally:
        await client.close()


async def main() -> None:
    container = Container()
    container.register(
        AsyncClient,
        factory=client_factory,
        lifetime=Lifetime.SCOPED_SINGLETON,
        scope="request",
    )

    async with container.start_scope("request") as scope:
        await scope.aresolve(AsyncClient)


asyncio.run(main())
```

## Global container context

For larger apps, `container_context` provides a context-local global container.

```python
"""Basic diwire usage examples."""
from dataclasses import dataclass
from typing import Annotated

from diwire import Container, FromDI, container_context


@container_context.register()
@dataclass
class Service:
    name: str = "diwire"


@container_context.resolve()
def greet(service: Annotated[Service, FromDI()]) -> str:
    return f"hello {service.name}"


container = Container()
container_context.set_current(container)


print(greet())
```

## API at a glance

- `Container`: `register`, `resolve`, `aresolve`, `start_scope`, `compile`
- `Lifetime`: `TRANSIENT`, `SINGLETON`, `SCOPED_SINGLETON`
- `FromDI`: `Annotated[T, FromDI()]` parameter marker
- `container_context`: context-local global container
- `Component` and `ServiceKey`: named registrations

## Performance

`Container.compile()` precompiles providers to reduce reflection and dict lookups. By default, the container auto-compiles on first resolve (set `auto_compile=False` to disable) and auto-registers constructor-injected types using `autoregister_default_lifetime`.

## Examples

See [`examples/README.md`](examples/README.md) for a guided tour of patterns, async usage, FastAPI-style integration, and error handling.

## License

MIT
