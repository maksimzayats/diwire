# diwire

**Type-driven dependency injection for Python. Zero dependencies. Zero boilerplate.**

[![PyPI version](https://img.shields.io/pypi/v/diwire.svg)](https://pypi.org/project/diwire/)
[![Python versions](https://img.shields.io/pypi/pyversions/diwire.svg)](https://pypi.org/project/diwire/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![codecov](https://codecov.io/gh/MaksimZayats/diwire/graph/badge.svg)](https://codecov.io/gh/MaksimZayats/diwire)
[![Docs](https://img.shields.io/badge/docs-diwire.dev-blue)](https://docs.diwire.dev)

diwire is a dependency injection container for Python 3.10+ that builds your object graph from type hints. It supports
scopes + deterministic cleanup, async resolution, open generics, fast steady-state resolution via compiled
resolvers, and free-threaded Python (no-GIL) — all with zero runtime dependencies.
The default registration lifetime is ``Lifetime.SCOPED`` (root-scoped caching by default).

## Why diwire

- **Zero runtime dependencies**: easy to adopt anywhere. ([Why diwire](https://docs.diwire.dev/why-diwire/))
- **Compiled resolver**: ``compile()`` generates a resolver specialized to your registrations. ([Compilation](https://docs.diwire.dev/core/compilation/))
- **Scopes + deterministic cleanup**: generator/async-generator providers clean up on scope exit. ([Scopes](https://docs.diwire.dev/core/scopes/))
- **Async resolution**: ``aresolve()`` mirrors ``resolve()`` and async providers are first-class. ([Async](https://docs.diwire.dev/core/async/))
- **Open generics**: register once, resolve for many type parameters. ([Open generics](https://docs.diwire.dev/core/open-generics/))
- **Function injection**: ``Injected[T]`` and ``FromContext[T]`` for ergonomic handlers. ([Function injection](https://docs.diwire.dev/core/function-injection/))
- **Named components + collect-all**: ``Component(\"name\")`` and ``All[T]``. ([Components](https://docs.diwire.dev/core/components/))
- **Concurrency + free-threaded builds**: configurable locking via ``LockMode``. ([Concurrency](https://docs.diwire.dev/howto/advanced/concurrency/))

## Performance (benchmarked)

Benchmarks + methodology live in the docs: [Performance](https://docs.diwire.dev/howto/advanced/performance/).

In this benchmark suite on CPython ``3.12.5`` (Apple M1 Pro, strict mode):

- Speedup over ``rodi`` ranges from **1.22×** to **2.19×**.
- Speedup over ``dishka`` ranges from **1.81×** to **7.76×**.
- Resolve-only comparisons (includes ``punq`` in non-scope scenarios): speedup ranges from **3.31×** to **268.84×**.

Results vary by environment, Python version, and hardware. Re-run ``make benchmark-report`` and
``make benchmark-report-resolve`` on your target runtime before drawing final conclusions for production workloads.

## Installation

```bash
uv add diwire
```

```bash
pip install diwire
```

## Quick start (auto-wiring)

Define your classes. Resolve the top-level one. diwire figures out the rest.

```python
from dataclasses import dataclass

from diwire import Container


@dataclass
class Database:
    host: str = "localhost"


@dataclass
class UserRepository:
    db: Database


@dataclass
class UserService:
    repo: UserRepository


container = Container()
service = container.resolve(UserService)
print(service.repo.db.host)  # => localhost
```

## Registration

Use explicit registrations when you need configuration objects, interfaces/protocols, cleanup, or multiple
implementations.

**Strict mode (recommended for production):**

```python
from diwire import Container

container = Container(
    )
```

```python
from typing import Protocol

from diwire import Container, Lifetime


class Clock(Protocol):
    def now(self) -> str: ...


class SystemClock:
    def now(self) -> str:
        return "now"


container = Container()
container.add_concrete(
    SystemClock,
    provides=Clock,
    lifetime=Lifetime.SCOPED,
)

print(container.resolve(Clock).now())  # => now
```

Register factories directly:

```python
from diwire import Container

container = Container()


def build_answer() -> int:
    return 42

container.add_factory(build_answer)

print(container.resolve(int))  # => 42
```

## Scopes & cleanup

Use `Lifetime.SCOPED` for per-request/per-job caching. Use generator/async-generator providers for deterministic
cleanup on scope exit.

```python
from collections.abc import Generator

from diwire import Container, Lifetime, Scope


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
container.add_generator(
    session_factory,
    provides=Session,
    scope=Scope.REQUEST,
    lifetime=Lifetime.SCOPED,
)

with container.enter_scope() as request_scope:
    session = request_scope.resolve(Session)
    print(session.closed)  # => False

print(session.closed)  # => True
```

## Function injection

Mark injected parameters as `Injected[T]` and wrap callables with `@container.inject`.

```python
from diwire import Container, Injected


class Service:
    def run(self) -> str:
        return "ok"


container = Container()


@container.inject
def handler(service: Injected[Service]) -> str:
    return service.run()


print(handler())  # => ok
```

## Named components

Use `Annotated[T, Component("name")]` when you need multiple registrations for the same base type.
For registration ergonomics, you can also pass `component="name"` to `add_*` methods.

```python
from typing import Annotated, TypeAlias

from diwire import All, Component, Container


class Cache:
    def __init__(self, label: str) -> None:
        self.label = label


PrimaryCache: TypeAlias = Annotated[Cache, Component("primary")]
FallbackCache: TypeAlias = Annotated[Cache, Component("fallback")]


container = Container()
container.add_instance(Cache(label="redis"), provides=Cache, component="primary")
container.add_instance(Cache(label="memory"), provides=Cache, component="fallback")

print(container.resolve(PrimaryCache).label)  # => redis
print(container.resolve(FallbackCache).label)  # => memory
print([cache.label for cache in container.resolve(All[Cache])])  # => ['redis', 'memory']
```

Resolution/injection keys are still `Annotated[..., Component(...)]` at runtime.

## container_context (optional)

If you can't (or don't want to) pass a `Container` everywhere, use `container_context`.

`container_context` stores one shared active container per `ContainerContext` instance (process-global for that
instance). It also supports deferred replay: registrations made before binding are recorded and replayed when you later
call `set_current(...)`.

```python
from diwire import Container, Injected, container_context


class Service:
    def run(self) -> str:
        return "ok"


@container_context.inject
def handler(service: Injected[Service]) -> str:
    return service.run()


container = Container()
container_context.set_current(container)

print(handler())  # => ok
```

## Stability

diwire targets a stable, small public API.

- Backward-incompatible changes only happen in major releases.
- Deprecations are announced first and kept for at least one minor release (when practical).

## Docs

- [Tutorial (runnable examples)](https://docs.diwire.dev/howto/examples/)
- [Core concepts](https://docs.diwire.dev/core/)
- [API reference](https://docs.diwire.dev/reference/)

## License

MIT. See [LICENSE](LICENSE).
