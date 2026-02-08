from types import TracebackType
from typing import Any, Protocol, TypeVar, overload

from typing_extensions import Self

from diwire.scope import BaseScope

T = TypeVar("T")


class ResolverProtocol(Protocol):
    """Protocol for a dependency resolver.

    Used with the dependency injection container to resolve dependencies.
    In the case of scoped dependencies, a resolver with cache it after the first resolution.
    The cache will replace the `resolve_<dependency_{{ slot }}>` method in the container with a `lambda` returning the cached instance.
    """

    def __init__(
        self,
        **previous_resolvers: "ResolverProtocol",
    ) -> None:
        """Initialize the resolver with any previous resolvers it may depend on."""

    @overload
    def resolve(self, dependency: type[T]) -> T: ...

    @overload
    def resolve(self, dependency: Any) -> Any: ...

    def resolve(self, dependency: Any) -> Any:
        """Resolve the given dependency and return its instance."""

    def enter_scope(self, scope: BaseScope) -> "ResolverProtocol":
        """Enter a new scope and return a new resolver for that scope."""

    def __enter__(self) -> Self:
        """Enter the resolver context."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the resolver context and perform any necessary cleanup.

        Cleanup will happen ONLY if the resolver created resources that need to be cleaned up.
        Like context managers or generators.
        """

    def __aenter__(self) -> Self:
        """Asynchronously enter the resolver context."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Asynchronously exit the resolver context and perform any necessary cleanup.

        Cleanup will happen ONLY if the resolver created resources that need to be cleaned up.
        Like context managers or generators.
        """
