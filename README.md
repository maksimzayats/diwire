# diwire

**Modern dependency injection for Python**

[![PyPI version](https://img.shields.io/pypi/v/diwire.svg)](https://pypi.org/project/diwire/)
[![Python versions](https://img.shields.io/pypi/pyversions/diwire.svg)](https://pypi.org/project/diwire/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A lightweight, type-safe dependency injection container with automatic wiring, scoped lifetimes, and zero dependencies.

## Features

- **Automatic constructor injection** - resolves entire dependency chains from type hints
- **Function injection** - inject dependencies into function parameters with `FromDI()`
- **Scoped lifetimes** - transient, singleton, and request/session-scoped instances
- **Generator factories** - automatic resource cleanup when scopes exit
- **Circular dependency detection** - clear error messages showing the full chain
- **Thread & async safe** - works seamlessly with threading and asyncio
- **Zero dependencies** - just Python 3.10+

## Installation

```bash
uv add diwire
```

## Quick Start

```python
from dataclasses import dataclass
from diwire import Container, Lifetime


@dataclass
class Database:
    host: str = "localhost"


@dataclass
class UserRepository:
    db: Database  # Injected automatically


@dataclass
class UserService:
    repo: UserRepository  # Entire chain resolved


container = Container(
    # Set default lifetime for auto-registered types
    autoregister_default_lifetime=Lifetime.TRANSIENT,
)
service = container.resolve(UserService)
# UserService -> UserRepository -> Database all wired automatically

print(service.repo.db.host)  # "localhost"
```

## Function Injection

Mark parameters with `FromDI()` to inject dependencies while keeping other parameters caller-provided:

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
    to: str,  # Provided by caller
    *,
    mailer: Annotated[EmailService, FromDI()],  # Injected
) -> str:
    return mailer.send(to, "Hello!")


container = Container()
send = container.resolve(send_email)
result = send(to="user@example.com")  # mailer injected automatically

print(result)  # "Sent 'Hello!' to user@example.com via smtp.example.com"
```

## Scoped Dependencies

Manage request/session-level instances with scopes:

```python
from enum import Enum
from diwire import Container, Lifetime


class Scope(str, Enum):
    REQUEST = "request"


class DbSession:
    def __init__(self) -> None:
        self.session_id = id(self)


container = Container()
container.register(DbSession, lifetime=Lifetime.SCOPED_SINGLETON, scope=Scope.REQUEST)

with container.start_scope(Scope.REQUEST) as scope:
    session1 = scope.resolve(DbSession)
    session2 = scope.resolve(DbSession)
    assert session1 is session2  # Same instance within scope
    print(f"Same session: {session1.session_id}")
```

## Examples

See the [examples/](examples/) directory for more patterns including:

- Registration methods (class, factory, instance)
- Lifetime management
- Named components
- Repository pattern with unit of work
- Generator factories for resource cleanup

## License

MIT
