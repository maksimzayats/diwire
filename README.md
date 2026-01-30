# diwire - dependency injection for Python

**Type-safe dependency injection with automatic wiring, scoped lifetimes, and async-safe factories.**

[![PyPI version](https://img.shields.io/pypi/v/diwire.svg)](https://pypi.org/project/diwire/)
[![Python versions](https://img.shields.io/pypi/pyversions/diwire.svg)](https://pypi.org/project/diwire/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![codecov](https://codecov.io/gh/MaksimZayats/diwire/graph/badge.svg)](https://codecov.io/gh/MaksimZayats/diwire)

`diwire` is a lightweight DI container for Python 3.10+ that resolves dependency graphs from type hints, supports scoped lifetimes, and cleans up resources via generator factories. It is async-first, thread-safe (including free-threaded Python 3.13t+), and has zero runtime dependencies.

## Why diwire

- **Automatic wiring** from type hints (constructor and function injection)
- **Scoped lifetimes** for request/session workflows
- **Generator factories** with cleanup on scope exit
- **Async support** with `aresolve()` and async factories
- **Interface + component registration** for multiple implementations
- **Free-threaded Python** (no-GIL) support out of the box
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

You can register classes, factories, or instances. `concrete_class` lets you register by interface or abstract base class.

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
```

## Open generics

Register open generic factories and resolve closed generics with type-safe validation. Type arguments can be
injected by annotating parameters as `type[T]`, and TypeVar bounds/constraints are enforced at resolution time.

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


print(container.resolve(AnyBox[int]))
print(container.resolve(ModelBox[Model]))
```

## Function injection

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
    return mailer.send(to, "Hello!")


container = Container()
send = container.resolve(send_email)
print(send(to="user@example.com"))
```

## Scopes and cleanup

Use scopes to manage request/session lifetimes. Generator factories clean up automatically when the scope exits.

**Important:** Cleanup code in generator factories must be wrapped in `try/finally` blocks. When a scope exits, the container calls `close()` (sync) or `aclose()` (async) on generators, which raises `GeneratorExit` at the `yield` point. Without `try/finally`, code after `yield` will not execute. This is standard Python generator behavior, used by FastAPI's `Depends`, pytest fixtures, and other frameworks.

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
        # Cleanup code MUST be in finally block to run on scope exit
        session.close()


container = Container()
container.register(Session, factory=session_factory, lifetime=Lifetime.SCOPED, scope="request")

with container.enter_scope("request") as scope:
    session = scope.resolve(Session)
    assert session.closed is False

# Or close scopes by name (closes child scopes automatically)
container.enter_scope("app")
container.enter_scope("request")
container.close_scope("app")  # Closes both "request" and "app" in LIFO order
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
        # Cleanup code MUST be in finally block to run on scope exit
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
        await scope.aresolve(AsyncClient)


asyncio.run(main())
```

## Global container context

For larger apps, `container_context` provides a context-local global container.

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


print(greet())
```

## API at a glance

- `Container`: `register`, `resolve`, `aresolve`, `enter_scope`, `close_scope`, `aclose_scope`, `compile`
- `Lifetime`: `TRANSIENT`, `SINGLETON`, `SCOPED`
- `Injected`: `Annotated[T, Injected()]` parameter marker
- `container_context`: context-local global container
- `Component` and `ServiceKey`: named registrations

## Performance

`Container.compile()` precompiles providers to reduce reflection and dict lookups. By default, the container auto-compiles on first resolve (set `auto_compile=False` to disable) and auto-registers constructor-injected types using `autoregister_default_lifetime`.

## Examples

See [`examples/README.md`](examples/README.md) for a guided tour of patterns, async usage, FastAPI-style integration, and error handling.

## License

MIT
