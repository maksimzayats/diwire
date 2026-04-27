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

## Frameworks & integrations

- Web: [FastAPI](https://docs.diwire.dev/howto/web/fastapi.html), [Litestar](https://docs.diwire.dev/howto/web/litestar.html),
  [aiohttp](https://docs.diwire.dev/howto/web/aiohttp.html), [Starlette](https://docs.diwire.dev/howto/web/starlette.html),
  [Flask](https://docs.diwire.dev/howto/web/flask.html), [Django](https://docs.diwire.dev/howto/web/django.html)
- Tasks: [Celery](https://docs.diwire.dev/howto/web/celery.html)
- Testing: [pytest plugin (Injected parameters)](https://docs.diwire.dev/howto/testing/pytest.html)
- Config: [pydantic-settings](https://docs.diwire.dev/howto/examples/pydantic-settings.html)
- Overview: [Integrations](https://docs.diwire.dev/core/integrations.html)

## Installation

```bash
uv add diwire
```

## Why diwire

- **Zero runtime dependencies**: easy to adopt anywhere. ([Why diwire](https://docs.diwire.dev/why-diwire.html))
- **Scopes + deterministic cleanup**: generator/async-generator providers clean up on scope exit. ([Scopes](https://docs.diwire.dev/core/scopes.html))
- **Async resolution**: ``aresolve()`` mirrors ``resolve()`` and async providers are first-class. ([Async](https://docs.diwire.dev/core/async.html))
- **Open generics**: register once, resolve for many type parameters. ([Open generics](https://docs.diwire.dev/core/open-generics.html))
- **Function injection**: ``Injected[T]`` for ergonomic handlers. ([Function injection](https://docs.diwire.dev/core/function-injection.html))
- **Framework/task support**: request/job scope patterns for FastAPI, Litestar, aiohttp, Starlette, Flask, Django, and Celery. ([Integrations](https://docs.diwire.dev/core/integrations.html))
- **Named components + collect-all**: ``Component("name")`` and ``All[T]``. ([Components](https://docs.diwire.dev/core/components.html))
- **Concurrency + free-threaded builds**: configurable locking via ``LockMode``. ([Concurrency](https://docs.diwire.dev/howto/advanced/concurrency.html))

## Performance (benchmarked)

Benchmarks + methodology live in the docs: [Performance](https://docs.diwire.dev/howto/advanced/performance.html).

In this benchmark suite on CPython ``3.14.3`` (Apple M3 Pro, strict mode):

- diwire is the top performer across this suite, reaching up to **6.89×** vs ``rodi``, **30.79×** vs ``dishka``, and **4.40×** vs ``wireup``.
- Resolve-only comparisons (scope-capable libraries): diwire reaches up to **3.64×** (``rodi``), **4.14×** (``dishka``), and **3.10×** (``wireup``).
- Current benchmark totals: **11** full-suite scenarios and **5** resolve-only scenarios.

For quick local regression checks, run ``make benchmark`` (diwire-only).
For full cross-library runs, use ``make benchmark-comparison`` (raw suite) or
``make benchmark-report`` / ``make benchmark-report-resolve`` (report artifacts).

## Quick start (pure Python auto-wiring)

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

When provider setup needs injected state of its own, register a callable class instead of a function. The class
constructor receives dependencies, and the instance `__call__` produces the dependency value.

```python
from dataclasses import dataclass

from diwire import Container, Injected


@dataclass(frozen=True)
class Settings:
    endpoint: str


class Client:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint


@dataclass(kw_only=True)
class ClientFactory:
    settings: Injected[Settings]

    def __call__(self) -> Client:
        return Client(self.settings.endpoint)


container = Container()
container.add_instance(Settings(endpoint="https://api.example.test"))
container.add_factory_class(ClientFactory, provides=Client)

print(container.resolve(Client).endpoint)  # => https://api.example.test
```

The same pattern is available for cleanup providers: use `add_generator_class()` when `__call__` yields the resource,
or `add_context_manager_class()` when `__call__` returns a context manager.

## Scopes & cleanup

Use `Lifetime.SCOPED` for per-request/per-job caching. Use generator/async-generator providers for deterministic
cleanup on scope exit. If the provider needs constructor-injected state, use the class variants and put the cleanup
logic in `__call__`.

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

Static typing note: without a checker plugin, injected wrappers keep return types but accept permissive
arguments. For precise mypy signatures (optional injected params, strict non-injected params, optional
`diwire_resolver` kwarg), enable:

```toml
[tool.mypy]
plugins = ["diwire.integrations.mypy_plugin"]
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
from contextvars import ContextVar

from diwire import Container, Injected, Scope, resolver_context

current_user_id_var: ContextVar[int] = ContextVar("current_user_id", default=0)


def read_current_user_id() -> int:
    return current_user_id_var.get()


container = Container()
container.add_factory(read_current_user_id, provides=int, scope=Scope.REQUEST)


@resolver_context.inject(scope=Scope.REQUEST)
def handler(value: Injected[int]) -> int:
    return value


with container.enter_scope(Scope.REQUEST) as request_scope:
    token = current_user_id_var.set(7)
    try:
        print(handler(diwire_resolver=request_scope))  # => 7
    finally:
        current_user_id_var.reset(token)
```

## Stability

diwire targets a stable, small public API.

- Backward-incompatible changes only happen in major releases.
- Deprecations are announced first and kept for at least one minor release (when practical).

## Docs

- [Tutorial (runnable examples)](https://docs.diwire.dev/howto/examples/)
- [Web frameworks](https://docs.diwire.dev/howto/web/)
- [FastAPI quick start](https://docs.diwire.dev/quickstart-fastapi.html)
- [Examples (repo)](https://github.com/maksimzayats/diwire/blob/main/examples/README.md)
- [Core concepts](https://docs.diwire.dev/core/)
- [API reference](https://docs.diwire.dev/reference/)

## License

MIT. See [LICENSE](LICENSE).
