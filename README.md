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

## Why diwire

- **Zero runtime dependencies**: easy to adopt anywhere. ([Why diwire](https://docs.diwire.dev/why-diwire/))
- **Scopes + deterministic cleanup**: generator/async-generator providers clean up on scope exit. ([Scopes](https://docs.diwire.dev/core/scopes/))
- **Async resolution**: ``aresolve()`` mirrors ``resolve()`` and async providers are first-class. ([Async](https://docs.diwire.dev/core/async/))
- **Open generics**: register once, resolve for many type parameters. ([Open generics](https://docs.diwire.dev/core/open-generics/))
- **Function injection**: ``Injected[T]`` and ``FromContext[T]`` for ergonomic handlers. ([Function injection](https://docs.diwire.dev/core/function-injection/))
- **Named components + collect-all**: ``Component("name")`` and ``All[T]``. ([Components](https://docs.diwire.dev/core/components/))
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
from dataclasses import dataclass, field

from diwire import Container


@dataclass
class Database:
    host: str = field(default="localhost", init=False)


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

**Strict mode (opt-in):**

```python
from diwire import Container, DependencyRegistrationPolicy, MissingPolicy

container = Container(
    missing_policy=MissingPolicy.ERROR,
    dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
)
```

``Container()`` enables recursive auto-wiring by default. Use strict mode when you need full
control over registration and want missing dependencies to fail fast.

```python
from typing import Protocol

from diwire import Container, Lifetime


class Clock(Protocol):
    def now(self) -> str: ...


class SystemClock:
    def now(self) -> str:
        return "now"


container = Container()
container.add(
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

Mark injected parameters as `Injected[T]` and wrap callables with `@resolver_context.inject`.

```python
from diwire import Container, Injected, resolver_context


class Service:
    def run(self) -> str:
        return "ok"


container = Container()
container.add(Service)


@resolver_context.inject
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

## resolver_context (optional)

If you can't (or don't want to) pass a resolver everywhere, use `resolver_context`.
It is a `contextvars`-based helper used by `@resolver_context.inject` and (by default) by `Container` resolution methods.
Inside `with container.enter_scope(...):`, injected callables resolve from the bound scope resolver; otherwise they fall
back to the container registered as the `resolver_context` fallback (`Container(..., use_resolver_context=True)` is the
default).

```python
from diwire import Container, FromContext, Scope, resolver_context

container = Container()


@resolver_context.inject(scope=Scope.REQUEST)
def handler(value: FromContext[int]) -> int:
    return value


with container.enter_scope(Scope.REQUEST, context={int: 7}):
    print(handler())  # => 7
```

## Stability

diwire targets a stable, small public API.

- Backward-incompatible changes only happen in major releases.
- Deprecations are announced first and kept for at least one minor release (when practical).

## Docs

- [Tutorial (runnable examples)](https://docs.diwire.dev/howto/examples/)
- [Examples (repo)](https://github.com/maksimzayats/diwire/blob/main/examples/README.md)
- [Core concepts](https://docs.diwire.dev/core/)
- [API reference](https://docs.diwire.dev/reference/)

## License

MIT. See [LICENSE](LICENSE).
