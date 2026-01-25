"""Global container context using Python's contextvars for lazy proxying."""

from __future__ import annotations

import inspect
import types
from collections.abc import Callable, Coroutine
from contextvars import ContextVar, Token
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar, overload

from diwire.exceptions import DIWireContainerNotSetError

if TYPE_CHECKING:
    from diwire.container import Container

# Import signature builder to exclude FromDI parameters from signature
from diwire.container import _build_signature_without_fromdi

T = TypeVar("T")

_current_container: ContextVar[Container | None] = ContextVar(
    "diwire_current_container",
    default=None,
)


class _ContextInjected:
    """A callable wrapper that resolves dependencies from the context container.

    Similar to Injected, but lazily gets the container from context on each call.
    """

    def __init__(
        self,
        func: Callable[..., Any],
        proxy: ContainerContextProxy,
    ) -> None:
        self._func = func
        self._proxy = proxy
        self._injected: Any | None = None

        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., Any] = func

        # Build signature at decoration time by detecting FromDI in annotations
        # This allows frameworks like FastAPI to correctly identify parameters
        self.__signature__ = _build_signature_without_fromdi(func)

    def _get_injected(self) -> Any:
        """Get the Injected wrapper from the current container."""
        container = self._proxy.get_current()
        return container.resolve(self._func)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        injected = self._get_injected()
        return injected(*args, **kwargs)

    def __repr__(self) -> str:
        return f"_ContextInjected({self._func!r})"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return types.MethodType(self, obj)


class _ContextScopedInjected:
    """A callable wrapper that creates a new scope from context container for each call.

    Similar to ScopedInjected, but lazily gets the container from context on each call.
    """

    def __init__(
        self,
        func: Callable[..., Any],
        proxy: ContainerContextProxy,
        scope_name: str,
    ) -> None:
        self._func = func
        self._proxy = proxy
        self._scope_name = scope_name

        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., Any] = func

        # Build signature at decoration time by detecting FromDI in annotations
        # This allows frameworks like FastAPI to correctly identify parameters
        self.__signature__ = _build_signature_without_fromdi(func)

    def _get_scoped_injected(self) -> Any:
        """Get the ScopedInjected wrapper from the current container."""
        container = self._proxy.get_current()
        return container.resolve(self._func, scope=self._scope_name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        scoped_injected = self._get_scoped_injected()
        return scoped_injected(*args, **kwargs)

    def __repr__(self) -> str:
        return f"_ContextScopedInjected({self._func!r}, scope={self._scope_name!r})"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return types.MethodType(self, obj)


class _AsyncContextInjected:
    """A callable wrapper that resolves dependencies from the context container for async functions.

    Similar to AsyncInjected, but lazily gets the container from context on each call.
    """

    def __init__(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        proxy: ContainerContextProxy,
    ) -> None:
        self._func = func
        self._proxy = proxy

        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., Coroutine[Any, Any, Any]] = func

        # Build signature at decoration time by detecting FromDI in annotations
        # This allows frameworks like FastAPI to correctly identify parameters
        self.__signature__ = _build_signature_without_fromdi(func)

    def _get_async_injected(self) -> Any:
        """Get the AsyncInjected wrapper from the current container."""
        container = self._proxy.get_current()
        return container.resolve(self._func)

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        async_injected = self._get_async_injected()
        return await async_injected(*args, **kwargs)

    def __repr__(self) -> str:
        return f"_AsyncContextInjected({self._func!r})"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return types.MethodType(self, obj)


class _AsyncContextScopedInjected:
    """A callable wrapper that creates a new async scope from context container for each call.

    Similar to AsyncScopedInjected, but lazily gets the container from context on each call.
    """

    def __init__(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        proxy: ContainerContextProxy,
        scope_name: str,
    ) -> None:
        self._func = func
        self._proxy = proxy
        self._scope_name = scope_name

        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., Coroutine[Any, Any, Any]] = func

        # Build signature at decoration time by detecting FromDI in annotations
        # This allows frameworks like FastAPI to correctly identify parameters
        self.__signature__ = _build_signature_without_fromdi(func)

    def _get_async_scoped_injected(self) -> Any:
        """Get the AsyncScopedInjected wrapper from the current container."""
        container = self._proxy.get_current()
        return container.resolve(self._func, scope=self._scope_name)

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        async_scoped_injected = self._get_async_scoped_injected()
        return await async_scoped_injected(*args, **kwargs)

    def __repr__(self) -> str:
        return f"_AsyncContextScopedInjected({self._func!r}, scope={self._scope_name!r})"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return types.MethodType(self, obj)


class ContainerContextProxy:
    """Lazy proxy that forwards calls to the current container from context.

    This allows setting up decorators before the container is configured,
    with the actual container lookup happening at call time.
    """

    # Fallback for when contextvar doesn't propagate (e.g., asyncio.run())
    # See: https://github.com/python/cpython/issues/102609
    _fallback_container: Container | None = None

    def set_current(self, container: Container) -> Token[Container | None]:
        """Set the current container in the context.

        Note: Also stores in a class-level fallback because Python's asyncio.run()
        creates a fresh context that doesn't inherit contextvar values.

        Args:
            container: The container to set as current.

        Returns:
            A token that can be used to reset the container.

        """
        ContainerContextProxy._fallback_container = container
        return _current_container.set(container)

    def get_current(self) -> Container:
        """Get the current container from the context.

        Tries contextvar first, then falls back to class-level storage.

        Returns:
            The current container.

        Raises:
            DIWireContainerNotSetError: If no container has been set.

        """
        container = _current_container.get()
        if container is None:
            # Fallback when contextvar not propagated (e.g., asyncio.run())
            container = self._fallback_container
        if container is None:
            raise DIWireContainerNotSetError
        return container

    def reset(self, token: Token[Container | None]) -> None:
        """Reset the container to its previous value.

        Args:
            token: The token returned by set_current.

        """
        _current_container.reset(token)
        # Also reset fallback if contextvar is now None
        if _current_container.get() is None:
            self._fallback_container = None

    # Decorator overloads
    @overload
    def resolve(
        self,
        key: None = None,
        *,
        scope: str,
    ) -> Callable[[Callable[..., Any]], Any]: ...

    @overload
    def resolve(
        self,
        key: None = None,
        *,
        scope: None = None,
    ) -> Callable[[Callable[..., Any]], Any]: ...

    @overload
    def resolve(self, key: type[T], *, scope: None = None) -> T: ...

    @overload
    def resolve(self, key: type[T], *, scope: str) -> T: ...

    @overload
    def resolve(self, key: Callable[..., Any], *, scope: None = None) -> Any: ...

    @overload
    def resolve(self, key: Callable[..., Any], *, scope: str) -> Any: ...

    @overload
    def resolve(self, key: Any, *, scope: str | None = None) -> Any: ...

    def resolve(self, key: Any | None = None, *, scope: str | None = None) -> Any:
        """Resolve a service or create a dependency-injected wrapper.

        When called with key=None, returns a decorator that can be applied to
        functions to enable dependency injection with lazy container lookup.

        When called with a type, resolves and returns a service instance from
        the current container.

        Args:
            key: The service key to resolve, or None for decorator usage.
            scope: Optional scope name for scoped resolution.

        Returns:
            A service instance, or a wrapper for function decoration.

        Examples:
            # Decorator usage (container looked up at call time):
            @container_context.resolve(scope="request")
            async def handler(service: Annotated[Service, FromDI()]) -> dict:
                ...

            # Direct resolution:
            service = container_context.resolve(Service)

        """
        # DECORATOR PATTERN: resolve(scope="...") or resolve() returns decorator
        if key is None:

            def decorator(func: Callable[..., Any]) -> Any:
                return self.resolve(func, scope=scope)

            return decorator

        # For callable types (functions), create lazy wrappers
        if callable(key) and not isinstance(key, type):
            is_async_func = inspect.iscoroutinefunction(key)

            if scope is not None:
                if is_async_func:
                    return _AsyncContextScopedInjected(key, self, scope)
                return _ContextScopedInjected(key, self, scope)
            if is_async_func:
                return _AsyncContextInjected(key, self)
            return _ContextInjected(key, self)

        # For types and other keys, delegate to the current container
        return self.get_current().resolve(key, scope=scope)

    def aresolve(self, key: type[T], *, scope: str | None = None) -> Coroutine[Any, Any, T]:
        """Asynchronously resolve a service from the current container.

        Args:
            key: The service key to resolve.
            scope: Optional scope name for scoped resolution.

        Returns:
            A coroutine that resolves to the service instance.

        """
        return self.get_current().aresolve(key, scope=scope)

    def register(self, *args: Any, **kwargs: Any) -> None:
        """Register a service with the current container.

        Delegates to the current container's register method.
        """
        return self.get_current().register(*args, **kwargs)

    def start_scope(self, scope_name: str | None = None) -> Any:
        """Start a new scope on the current container.

        Args:
            scope_name: Optional name for the scope.

        Returns:
            A ScopedContainer context manager.

        """
        return self.get_current().start_scope(scope_name)

    def compile(self) -> None:
        """Compile the current container for optimized resolution."""
        return self.get_current().compile()


container_context = ContainerContextProxy()
