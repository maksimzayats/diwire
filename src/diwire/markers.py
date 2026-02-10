from typing import TYPE_CHECKING, Annotated, Any, NamedTuple, TypeVar, Union, get_args, get_origin

T = TypeVar("T")


class Component(NamedTuple):
    """A marker used to distinguish different components for the same type.

    Usage:
        class Database: ...

        Replica: TypeAlias = Annotated[Database, Component("replica")]
        Primary: TypeAlias = Annotated[Database, Component("primary")]
    """

    value: str


class InjectedMarker:
    """A marker used to indicate a parameter should be injected from the DI container.

    Used to identify parameters that need to be removed from callable signatures
    when resolving dependencies.
    """


if TYPE_CHECKING:
    Injected = Union[T, T]  # noqa: UP007,PYI016
    """Type wrapper to indicate a parameter should be injected from the DI container.

    Usage:
        def my_function(service: Injected[ServiceA], value: int) -> None:
            ...

    At runtime, Injected[T] resolves to Annotated[T, InjectedMarker()].
    """

else:

    class Injected:
        """Type wrapper to indicate a parameter should be injected from the DI container.

        Usage:
            def my_function(service: Injected[ServiceA], value: int) -> None:
                ...

        At runtime, Injected[T] resolves to Annotated[T, InjectedMarker()].
        """

        def __class_getitem__(cls, item: T) -> Annotated[T, InjectedMarker]:
            if get_origin(item) is Annotated:
                args = get_args(item)
                inner = args[0]
                metadata = args[1:]
                return _build_annotated((inner, *metadata, InjectedMarker()))
            return _build_annotated((item, InjectedMarker()))


def _build_annotated(params: tuple[object, ...]) -> Any:
    """Return Annotated[...] with a pre-built params tuple (Py 3.10+ compatible)."""
    try:
        return Annotated.__class_getitem__(params)  # type: ignore[attr-defined]
    except AttributeError:
        return Annotated.__getitem__(params)  # type: ignore[attr-defined]
