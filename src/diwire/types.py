from collections.abc import Callable, Generator
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any, TypeAlias, TypeVar, Union, get_args, get_origin

from typing_extensions import Self

from diwire.exceptions import DIWireInjectedInstantiationError


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

T = TypeVar("T")


class _InjectedMarker:
    """Internal marker used to tag injected parameters in Annotated metadata."""


def _build_annotated(params: tuple[object, ...]) -> Any:
    """Return Annotated[...] with a pre-built params tuple (Py 3.10+ compatible)."""
    try:
        return Annotated.__class_getitem__(params)  # type: ignore[attr-defined]
    except AttributeError:
        return Annotated.__getitem__(params)  # type: ignore[attr-defined]


if TYPE_CHECKING:
    Injected = Union[T, T]  # noqa: UP007,PYI016
else:

    class Injected:
        """Type wrapper to indicate a parameter should be injected from the DI container.

        Usage:
            def my_function(service: Injected[ServiceA], value: int) -> None:
                ...

        At runtime, Injected[T] resolves to Annotated[T, _InjectedMarker()].
        """

        def __new__(cls, *_args: object, **_kwargs: object) -> Self:
            """Prevent instantiation; use Injected[T] instead."""
            raise DIWireInjectedInstantiationError

        def __class_getitem__(cls, item: T) -> Annotated[T, _InjectedMarker]:
            if get_origin(item) is Annotated:
                args = get_args(item)
                inner = args[0]
                metadata = args[1:]
                return _build_annotated((inner, *metadata, _InjectedMarker()))
            return _build_annotated((item, _InjectedMarker()))
