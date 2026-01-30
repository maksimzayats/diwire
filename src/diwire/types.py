from collections.abc import Callable, Generator
from enum import Enum
from typing import Any, TypeAlias


class Lifetime(str, Enum):
    """Defines the lifetime of a service in the container."""

    TRANSIENT = "transient"
    """A new instance is created every time the service is requested."""

    SINGLETON = "singleton"
    """A single instance is created and shared for the lifetime of the container."""

    SCOPED = "scoped"
    """Instance is shared within a scope, different instances across scopes."""


class FactoryClassProtocol:
    """Protocol for factory classes that create instances of a specific type."""

    def __call__(self, *args: Any, **kwargs: Any) -> "FactoryReturn": ...  # noqa: D102


FactoryReturn: TypeAlias = Any | Generator[Any, None, None]
"""Return type for factories, including generator factories."""


FactoryFunction: TypeAlias = Callable[..., FactoryReturn]
"""A type alias for factory functions that create instances of a specific type."""

Factory: TypeAlias = type[FactoryClassProtocol] | FactoryFunction
"""A type alias for either a factory class or a factory function."""


class Injected:
    """Marker to indicate a parameter should be injected from the DI container.

    Usage:
        def my_function(service: Annotated[ServiceA, Injected()], value: int) -> None:
            ...

    For type checkers, Annotated[T, Injected()] is equivalent to T.
    At runtime, parameters marked with Injected will be automatically injected.
    """
