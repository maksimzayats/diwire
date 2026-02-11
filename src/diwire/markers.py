from typing import TYPE_CHECKING, Annotated, Any, NamedTuple, TypeVar, Union, get_args, get_origin

T = TypeVar("T")
_ANNOTATED_MARKER_MIN_ARGS = 2


class Component(NamedTuple):
    """A marker used to distinguish different components for the same type.

    Usage:
        class Database: ...

        Replica: TypeAlias = Annotated[Database, Component("replica")]
        Primary: TypeAlias = Annotated[Database, Component("primary")]
    """

    value: Any


class InjectedMarker:
    """A marker used to indicate a parameter should be injected from the DI container.

    Used to identify parameters that need to be removed from callable signatures
    when resolving dependencies.
    """


class FromContextMarker:
    """Marker that indicates dependency value should be taken from scope context."""


if TYPE_CHECKING:
    Injected = Union[T, T]  # noqa: UP007,PYI016
    """Type wrapper to indicate a parameter should be injected from the DI container.

    Usage:
        def my_function(service: Injected[ServiceA], value: int) -> None:
            ...

    At runtime, Injected[T] resolves to Annotated[T, InjectedMarker()].
    """

    FromContext = Union[T, T]  # noqa: UP007,PYI016
    """Type wrapper to indicate a parameter should be resolved from scope context.

    Usage:
        def my_function(value: FromContext[int]) -> None:
            ...

    At runtime, FromContext[T] resolves to Annotated[T, FromContextMarker()].
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

    class FromContext:
        """Type wrapper to indicate a parameter should come from scope context.

        Usage:
            def my_function(value: FromContext[int]) -> None:
                ...

        At runtime, FromContext[T] resolves to Annotated[T, FromContextMarker()].
        """

        def __class_getitem__(cls, item: T) -> Annotated[T, FromContextMarker]:
            if get_origin(item) is Annotated:
                args = get_args(item)
                inner = args[0]
                metadata = args[1:]
                return _build_annotated((inner, *metadata, FromContextMarker()))
            return _build_annotated((item, FromContextMarker()))


def is_from_context_annotation(annotation: Any) -> bool:
    """Return True when annotation is Annotated[..., FromContextMarker()]."""
    if get_origin(annotation) is not Annotated:
        return False
    annotation_args = get_args(annotation)
    if len(annotation_args) < _ANNOTATED_MARKER_MIN_ARGS:
        return False
    metadata = annotation_args[1:]
    return any(isinstance(item, FromContextMarker) for item in metadata)


def strip_from_context_annotation(annotation: Any) -> Any:
    """Strip FromContext marker while preserving non-context Annotated metadata."""
    if not is_from_context_annotation(annotation):
        return annotation

    annotation_args = get_args(annotation)
    parameter_type = annotation_args[0]
    metadata = annotation_args[1:]
    filtered_metadata = tuple(item for item in metadata if not isinstance(item, FromContextMarker))
    if not filtered_metadata:
        return parameter_type
    return _build_annotated((parameter_type, *filtered_metadata))


def _build_annotated(params: tuple[object, ...]) -> Any:
    """Return Annotated[...] with a pre-built params tuple (Py 3.10+ compatible)."""
    try:
        return Annotated.__class_getitem__(params)  # type: ignore[attr-defined]
    except AttributeError:
        return Annotated.__getitem__(params)  # type: ignore[attr-defined]
