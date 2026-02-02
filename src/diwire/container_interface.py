from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar, overload

from diwire.types import Factory, Lifetime

T = TypeVar("T")
C = TypeVar("C", bound=type)


class IContainer(ABC):
    """Interface for container-like objects."""

    # Overload 1: Bare class decorator - @container.register
    @overload
    @abstractmethod
    def register(self, key: C, /) -> C: ...

    # Overload 2: Bare factory function decorator - @container.register
    @overload
    @abstractmethod
    def register(self, key: Callable[..., T], /) -> Callable[..., T]: ...

    # Overload 3: Parameterized decorator without key - @container.register(lifetime=...)
    @overload
    @abstractmethod
    def register(
        self,
        key: None = None,
        /,
        factory: None = None,
        instance: None = None,
        lifetime: Lifetime = ...,
        scope: str | None = ...,
        is_async: bool | None = ...,  # noqa: FBT001
        concrete_class: type | None = ...,
    ) -> Callable[[T], T]: ...

    # Overload 4: Interface decorator - @container.register(Interface, lifetime=...)
    @overload
    @abstractmethod
    def register(
        self,
        key: type,
        /,
        *,
        lifetime: Lifetime = ...,
        scope: str | None = ...,
        is_async: bool | None = ...,
    ) -> Callable[[T], T]: ...

    # Overload 5: String key decorator - @container.register("key", lifetime=...)
    @overload
    @abstractmethod
    def register(
        self,
        key: str,
        /,
        *,
        lifetime: Lifetime = ...,
        scope: str | None = ...,
        is_async: bool | None = ...,
    ) -> Callable[[T], T]: ...

    # Overload 6: Direct call with explicit key - container.register(Interface, concrete_class=...)
    @overload
    @abstractmethod
    def register(
        self,
        key: Any,
        /,
        factory: Factory | None = ...,
        instance: Any | None = ...,
        lifetime: Lifetime = ...,
        scope: str | None = ...,
        is_async: bool | None = ...,  # noqa: FBT001
        concrete_class: type | None = ...,
    ) -> None: ...

    @abstractmethod
    def register(  # noqa: PLR0913
        self,
        key: Any | None = None,
        /,
        factory: Factory | None = None,
        instance: Any | None = None,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        scope: str | None = None,
        is_async: bool | None = None,  # noqa: FBT001
        concrete_class: type | None = None,
    ) -> Any:
        """Register a service with the container."""

    @overload
    @abstractmethod
    def resolve(
        self,
        key: None = None,
        *,
        scope: str,
    ) -> Callable[[Callable[..., Any]], Any]: ...

    @overload
    @abstractmethod
    def resolve(
        self,
        key: None = None,
        *,
        scope: None = None,
    ) -> Callable[[Callable[..., Any]], Any]: ...

    @overload
    @abstractmethod
    def resolve(self, key: type[T], *, scope: None = None) -> T: ...

    @overload
    @abstractmethod
    def resolve(self, key: type[T], *, scope: str) -> T: ...

    @overload
    @abstractmethod
    def resolve(
        self,
        key: Callable[..., Coroutine[Any, Any, T]],
        *,
        scope: None = None,
    ) -> Any: ...

    @overload
    @abstractmethod
    def resolve(
        self,
        key: Callable[..., Coroutine[Any, Any, T]],
        *,
        scope: str,
    ) -> Any: ...

    @overload
    @abstractmethod
    def resolve(self, key: Callable[..., T], *, scope: None = None) -> Any: ...

    @overload
    @abstractmethod
    def resolve(self, key: Callable[..., T], *, scope: str) -> Any: ...

    @overload
    @abstractmethod
    def resolve(self, key: Any, *, scope: str | None = None) -> Any: ...

    @abstractmethod
    def resolve(self, key: Any | None = None, *, scope: str | None = None) -> Any:
        """Resolve a service or create a dependency-injected wrapper."""

    @abstractmethod
    def aresolve(self, key: type[T], *, scope: str | None = None) -> Coroutine[Any, Any, T]:
        """Asynchronously resolve a service."""

    @abstractmethod
    def enter_scope(self, scope_name: str | None = None) -> IContainer:
        """Start a new scope."""

    @abstractmethod
    def compile(self) -> None:
        """Compile the container for optimized resolution."""

    @abstractmethod
    def close(self) -> None:
        """Close the container."""

    @abstractmethod
    async def aclose(self) -> None:
        """Asynchronously close the container."""

    @abstractmethod
    def close_scope(self, scope_name: str) -> None:
        """Close all active scopes that contain the given scope name."""

    @abstractmethod
    async def aclose_scope(self, scope_name: str) -> None:
        """Asynchronously close all active scopes that contain the given scope name."""
