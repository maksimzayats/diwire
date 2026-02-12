from collections.abc import Awaitable, Callable
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


class MaybeMarker:
    """Marker that indicates dependency is optional and may resolve to ``None``."""


class ProviderMarker(NamedTuple):
    """Marker for lazy resolver-bound provider callables."""

    dependency_key: Any
    is_async: bool


class AllMarker(NamedTuple):
    """Marker for collecting all implementations registered for a base dependency key."""

    dependency_key: Any


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

    Provider = Callable[[], T]
    """Mark a dependency as a resolver-bound lazy provider callable.

    At runtime ``Provider[T]`` becomes ``Annotated[T, ProviderMarker(...)]`` and resolves
    to ``Callable[[], T]`` bound to the injection-time resolver.
    """

    AsyncProvider = Callable[[], Awaitable[T]]
    """Mark a dependency as a resolver-bound async lazy provider callable.

    At runtime ``AsyncProvider[T]`` becomes ``Annotated[T, ProviderMarker(...)]`` and resolves
    to ``Callable[[], Awaitable[T]]`` bound to the injection-time resolver.
    """

    All = tuple[T, ...]
    """Resolve all implementations registered for a base dependency key.

    ``All[T]`` type-checks as ``tuple[T, ...]`` and always resolves to a tuple.
    It returns an empty tuple when no matching registrations exist.
    """

    Maybe = T | None  # type: ignore[misc]
    """Mark a dependency as explicitly optional.

    At runtime ``Maybe[T]`` becomes ``Annotated[T, MaybeMarker()]``.
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

    class Maybe:
        """Mark a dependency as explicitly optional.

        At runtime ``Maybe[T]`` resolves to ``Annotated[T, MaybeMarker()]``.
        """

        def __class_getitem__(cls, item: T) -> Annotated[T, MaybeMarker]:
            if get_origin(item) is Annotated:
                args = get_args(item)
                inner = args[0]
                metadata = args[1:]
                return _build_annotated((inner, *metadata, MaybeMarker()))
            return _build_annotated((item, MaybeMarker()))

    class Provider:
        """Mark a dependency for lazy resolver-bound sync provider injection."""

        def __class_getitem__(cls, item: T) -> Annotated[T, ProviderMarker]:
            return _build_provider_annotation(item=item, is_async=False)

    class AsyncProvider:
        """Mark a dependency for lazy resolver-bound async provider injection."""

        def __class_getitem__(cls, item: T) -> Annotated[T, ProviderMarker]:
            return _build_provider_annotation(item=item, is_async=True)

    class All:
        """Resolve all implementations registered for a base dependency key.

        At runtime ``All[T]`` resolves to ``Annotated[T, AllMarker(dependency_key=T)]`` and is
        detected by the resolver dispatch to collect the plain registration for ``T`` (if any)
        plus all component-qualified registrations keyed as ``Annotated[T, Component(...)]``.

        Notes:
            If you pass an ``Annotated[...]`` token (for example
            ``All[Annotated[T, Component('x')]]``), DIWire strips it to the base type ``T`` and
            produces the same token as ``All[T]``. Prefer using ``All[BaseType]``.

        """

        def __class_getitem__(cls, item: Any) -> Any:
            base_key = item
            if get_origin(item) is Annotated:
                args = get_args(item)
                base_key = args[0]
            return _build_annotated((base_key, AllMarker(dependency_key=base_key)))


def is_maybe_annotation(annotation: Any) -> bool:
    """Return True when annotation is Annotated[..., MaybeMarker()]."""
    if get_origin(annotation) is not Annotated:
        return False
    annotation_args = get_args(annotation)
    if len(annotation_args) < _ANNOTATED_MARKER_MIN_ARGS:
        return False
    metadata = annotation_args[1:]
    return any(isinstance(item, MaybeMarker) for item in metadata)


def strip_maybe_annotation(annotation: Any) -> Any:
    """Strip Maybe marker while preserving non-maybe Annotated metadata."""
    if not is_maybe_annotation(annotation):
        return annotation

    annotation_args = get_args(annotation)
    parameter_type = annotation_args[0]
    metadata = annotation_args[1:]
    filtered_metadata = tuple(item for item in metadata if not isinstance(item, MaybeMarker))
    if not filtered_metadata:
        return parameter_type
    return _build_annotated((parameter_type, *filtered_metadata))


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


def is_provider_annotation(annotation: Any) -> bool:
    """Return True when annotation is Annotated[..., ProviderMarker(...)]."""
    return _extract_provider_marker(annotation) is not None


def is_all_annotation(annotation: Any) -> bool:
    """Return True when annotation is Annotated[..., AllMarker(...)]."""
    return _extract_all_marker(annotation) is not None


def strip_provider_annotation(annotation: Any) -> Any:
    """Return inner dependency key for Provider/AsyncProvider annotations."""
    marker = _extract_provider_marker(annotation)
    if marker is None:
        return annotation
    return marker.dependency_key


def strip_all_annotation(annotation: Any) -> Any:
    """Return inner dependency key for All[...] annotations."""
    marker = _extract_all_marker(annotation)
    if marker is None:
        return annotation
    return marker.dependency_key


def is_async_provider_annotation(annotation: Any) -> bool:
    """Return True when annotation is AsyncProvider[...] marker."""
    marker = _extract_provider_marker(annotation)
    if marker is None:
        return False
    return marker.is_async


def component_base_key(annotation: Any) -> Any | None:
    """Return base dependency key for ``Annotated[Base, Component(...)]`` registrations."""
    if get_origin(annotation) is not Annotated:
        return None
    annotation_args = get_args(annotation)
    if len(annotation_args) < _ANNOTATED_MARKER_MIN_ARGS:
        return None
    metadata = annotation_args[1:]
    if not any(isinstance(item, Component) for item in metadata):
        return None
    return annotation_args[0]


def _extract_provider_marker(annotation: Any) -> ProviderMarker | None:
    if get_origin(annotation) is not Annotated:
        return None
    annotation_args = get_args(annotation)
    if len(annotation_args) < _ANNOTATED_MARKER_MIN_ARGS:
        return None
    metadata = annotation_args[1:]
    return next(
        (item for item in metadata if isinstance(item, ProviderMarker)),
        None,
    )


def _extract_all_marker(annotation: Any) -> AllMarker | None:
    if get_origin(annotation) is not Annotated:
        return None
    annotation_args = get_args(annotation)
    if len(annotation_args) < _ANNOTATED_MARKER_MIN_ARGS:
        return None
    metadata = annotation_args[1:]
    return next(
        (item for item in metadata if isinstance(item, AllMarker)),
        None,
    )


def _build_provider_annotation(*, item: T, is_async: bool) -> Annotated[T, ProviderMarker]:
    provider_marker = ProviderMarker(dependency_key=item, is_async=is_async)
    if get_origin(item) is Annotated:
        args = get_args(item)
        inner = args[0]
        metadata = args[1:]
        return _build_annotated((inner, *metadata, provider_marker))
    return _build_annotated((item, provider_marker))


def build_annotated_key(params: tuple[object, ...]) -> Any:
    """Return Annotated[...] with a pre-built params tuple (Py 3.10+ compatible)."""
    try:
        return Annotated.__class_getitem__(params)  # type: ignore[attr-defined]
    except AttributeError:
        return Annotated.__getitem__(params)  # type: ignore[attr-defined]


def _build_annotated(params: tuple[object, ...]) -> Any:
    return build_annotated_key(params)
