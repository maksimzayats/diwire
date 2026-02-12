from typing import TYPE_CHECKING, Annotated, Any, NamedTuple, TypeVar, Union, get_args, get_origin

T = TypeVar("T")
_ANNOTATED_MARKER_MIN_ARGS = 2


class Component(NamedTuple):
    """Differentiate multiple providers for the same base type.

    Attach ``Component`` metadata to ``typing.Annotated`` so DIWire treats each
    annotated key as distinct at runtime.

    Examples:
        .. code-block:: python

            from typing import Annotated, TypeAlias


            class Database: ...


            ReplicaDb: TypeAlias = Annotated[Database, Component("replica")]
            PrimaryDb: TypeAlias = Annotated[Database, Component("primary")]

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
    """Mark a parameter for container-driven injection.

    At runtime ``Injected[T]`` becomes ``Annotated[T, InjectedMarker()]``.
    Container wrappers hide these parameters from the public callable signature.

    Examples:
        .. code-block:: python

            @container.inject
            def run(service: Injected[Service], value: int) -> str:
                return service.handle(value)
    """

    FromContext = Union[T, T]  # noqa: UP007,PYI016
    """Mark a parameter to resolve from the current scope context mapping.

    At runtime ``FromContext[T]`` becomes ``Annotated[T, FromContextMarker()]``.
    Context lookups use the full annotation as the key. For plain values use
    ``FromContext[int]`` with ``context={int: ...}``. For component-scoped values
    use ``FromContext[Annotated[int, Component('name')]]`` with the matching
    annotated key in ``context``.

    Missing context keys fail during resolution with
    ``DIWireDependencyNotRegisteredError``.

    Examples:
        .. code-block:: python

            Priority = Annotated[int, Component("priority")]

            @container.inject(scope=Scope.REQUEST)
            def handler(
                request_id: FromContext[int],
                priority: FromContext[Priority],
            ) -> tuple[int, int]:
                return request_id, priority
    """

else:

    class Injected:
        """Mark a parameter for container-driven injection.

        At runtime ``Injected[T]`` resolves to ``Annotated[T, InjectedMarker()]``.

        Examples:
            .. code-block:: python

                @container.inject
                def run(service: Injected[Service], value: int) -> str:
                    return service.handle(value)

        """

        def __class_getitem__(cls, item: T) -> Annotated[T, InjectedMarker]:
            if get_origin(item) is Annotated:
                args = get_args(item)
                inner = args[0]
                metadata = args[1:]
                return _build_annotated((inner, *metadata, InjectedMarker()))
            return _build_annotated((item, InjectedMarker()))

    class FromContext:
        """Mark a parameter to resolve from scope context instead of providers.

        At runtime ``FromContext[T]`` resolves to
        ``Annotated[T, FromContextMarker()]``. The resolver uses the full
        annotation key, so ``FromContext[int]`` looks up ``int`` and
        ``FromContext[Annotated[int, Component('priority')]]`` looks up that
        annotated token.

        Missing context keys fail during resolution with
        ``DIWireDependencyNotRegisteredError``.

        Examples:
            .. code-block:: python

                Priority = Annotated[int, Component("priority")]


                @container.inject(scope=Scope.REQUEST)
                def handler(
                    request_id: FromContext[int],
                    priority: FromContext[Priority],
                ) -> tuple[int, int]:
                    return request_id, priority

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
