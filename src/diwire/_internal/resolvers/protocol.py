from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, overload

from diwire._internal.providers import ProvidersRegistrations
from diwire._internal.scope import BaseScope

if TYPE_CHECKING:
    from typing_extensions import Self

T = TypeVar("T")


class ResolverProtocol(Protocol):
    """Protocol for a dependency resolver."""

    @overload
    def resolve(self, dependency: type[T]) -> T: ...

    @overload
    def resolve(self, dependency: Any) -> Any: ...

    def resolve(self, dependency: Any) -> Any:
        """Resolve the given dependency and return its instance."""

    @overload
    async def aresolve(self, dependency: type[T]) -> T: ...

    @overload
    async def aresolve(self, dependency: Any) -> Any: ...

    async def aresolve(self, dependency: Any) -> Any:
        """Resolve the given dependency asynchronously and return its instance."""

    def enter_scope(
        self,
        scope: BaseScope | None = None,
        *,
        context: Mapping[Any, Any] | None = None,
    ) -> ResolverProtocol:
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

    def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        """Close the resolver by forwarding to ``__exit__`` with the given exception context."""

    async def aclose(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        """Asynchronously close the resolver by forwarding to ``__aexit__``."""


class BuildRootResolverFunctionProtocol(Protocol):
    """Protocol for a function that gets the root resolver for the given registrations."""

    def __call__(
        self,
        registrations: ProvidersRegistrations,
        *,
        cleanup_enabled: bool = True,
    ) -> ResolverProtocol:
        """Get the root resolver for the given registrations."""
