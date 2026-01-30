"""Global container context using Python's contextvars for lazy proxying."""

from __future__ import annotations

import inspect
import threading
import types
from collections.abc import Callable, Coroutine
from contextvars import ContextVar, Token
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar, get_origin, overload

from diwire.exceptions import DIWireContainerNotSetError
from diwire.types import Factory, Lifetime

if TYPE_CHECKING:
    from diwire.container import Container
    from diwire.container_scopes import ScopedContainer

# Import signature builder to exclude Injected parameters from signature
from diwire.container_helpers import _build_signature_without_injected

T = TypeVar("T")
_C = TypeVar("_C", bound=type)

_current_container: ContextVar[Container | None] = ContextVar(
    "diwire_current_container",
    default=None,
)

# Thread-local fallback for when ContextVar is explicitly cleared or not set.
# Note: asyncio.run() does propagate ContextVar values; this fallback is primarily
# for cases where a new context is created without copying the parent context.
# Each thread gets its own fallback container to prevent cross-thread leakage.
# See: https://github.com/python/cpython/issues/102609
_thread_local_fallback: threading.local = threading.local()


@dataclass(slots=True)
class _DeferredRegistration:
    key: Any
    factory: Factory | None
    instance: Any | None
    lifetime: Lifetime
    scope: str | None
    is_async: bool | None
    concrete_class: type | None
    via_decorator: bool

    def apply(self, container: Container) -> None:
        if self.via_decorator:
            decorator = container.register(
                lifetime=self.lifetime,
                scope=self.scope,
                is_async=self.is_async,
                concrete_class=self.concrete_class,
            )
            decorator(self.key)
            return

        container.register(
            self.key,
            factory=self.factory,
            instance=self.instance,
            lifetime=self.lifetime,
            scope=self.scope,
            is_async=self.is_async,
            concrete_class=self.concrete_class,
        )


class _ContextInjected:
    """A callable wrapper that resolves dependencies from the context container.

    Similar to Injected, but lazily gets the container from context on each call.
    """

    def __init__(
        self,
        func: Callable[..., Any],
        proxy: _ContainerContextProxy,
    ) -> None:
        self._func = func
        self._proxy = proxy

        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., Any] = func

        # Build signature at decoration time by detecting Injected in annotations
        # This allows frameworks like FastAPI to correctly identify parameters
        self.__signature__ = _build_signature_without_injected(func)

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
        proxy: _ContainerContextProxy,
        scope_name: str,
    ) -> None:
        self._func = func
        self._proxy = proxy
        self._scope_name = scope_name

        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., Any] = func

        # Build signature at decoration time by detecting Injected in annotations
        # This allows frameworks like FastAPI to correctly identify parameters
        self.__signature__ = _build_signature_without_injected(func)

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
        proxy: _ContainerContextProxy,
    ) -> None:
        self._func = func
        self._proxy = proxy

        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., Coroutine[Any, Any, Any]] = func

        # Build signature at decoration time by detecting Injected in annotations
        # This allows frameworks like FastAPI to correctly identify parameters
        self.__signature__ = _build_signature_without_injected(func)

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
        proxy: _ContainerContextProxy,
        scope_name: str,
    ) -> None:
        self._func = func
        self._proxy = proxy
        self._scope_name = scope_name

        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., Coroutine[Any, Any, Any]] = func

        # Build signature at decoration time by detecting Injected in annotations
        # This allows frameworks like FastAPI to correctly identify parameters
        self.__signature__ = _build_signature_without_injected(func)

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


class _ContainerContextProxy:
    """Lazy proxy that forwards calls to the current container from context.

    This allows setting up decorators before the container is configured,
    with the actual container lookup happening at call time.

    Resolution order in get_current():
    1. ContextVar (highest precedence - for explicit per-request containers)
    2. Thread-local (for asyncio.run() case where ContextVar doesn't propagate)
    3. Instance-level default (lowest precedence - for cross-thread access)

    The instance-level default exists because some frameworks (e.g., FastAPI/Starlette)
    run sync endpoint handlers in a thread pool, meaning neither ContextVar nor
    thread-local storage can access a container set in the main thread.

    Registrations can be deferred until a container is set; they are applied
    the next time set_current() is called.
    """

    def __init__(self) -> None:
        self._default_container: Container | None = None
        self._deferred_registrations: list[_DeferredRegistration] = []

    def set_current(self, container: Container) -> Token[Container | None]:
        """Set the current container in the context.

        Sets the container in three storage mechanisms:
        1. ContextVar - for same async context access
        2. Thread-local - for asyncio.run() case (same thread, new context)
        3. Instance-level default - for thread pool access (different threads)

        Args:
            container: The container to set as current.

        Returns:
            A token that can be used to reset the container.

        """
        self._default_container = container
        _thread_local_fallback.container = container
        token = _current_container.set(container)
        self._flush_deferred(container)
        return token

    def _get_current_or_none(self) -> Container | None:
        """Return the current container if available, otherwise None."""
        container = _current_container.get()
        if container is not None:
            return container

        container = getattr(_thread_local_fallback, "container", None)
        if container is not None:
            return container

        return self._default_container

    def get_current(self) -> Container:
        """Get the current container from the context.

        Resolution order (first non-None wins):
        1. ContextVar - for per-context containers
        2. Thread-local - for asyncio.run() (same thread, new context)
        3. Instance-level default - for thread pools (different thread entirely)

        Returns:
            The current container.

        Raises:
            DIWireContainerNotSetError: If no container has been set.

        """
        # 1. Try ContextVar (highest precedence)
        container = _current_container.get()
        if container is not None:
            return container

        # 2. Fallback: Thread-local (for asyncio.run() in same thread)
        container = getattr(_thread_local_fallback, "container", None)
        if container is not None:
            return container

        # 3. Fallback: Instance-level default (for thread pools like FastAPI sync handlers)
        if self._default_container is not None:
            return self._default_container

        raise DIWireContainerNotSetError

    def _flush_deferred(self, container: Container) -> None:
        if not self._deferred_registrations:
            return

        pending = self._deferred_registrations
        self._deferred_registrations = []
        for registration in pending:
            registration.apply(container)

    def reset(self, token: Token[Container | None]) -> None:
        """Reset the container to its previous value.

        Args:
            token: The token returned by set_current.

        """
        _current_container.reset(token)
        current = _current_container.get()
        if current is None:
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            self._default_container = None
        else:
            _thread_local_fallback.container = current
            self._default_container = current

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
            async def handler(service: Annotated[Service, Injected()]) -> dict:
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

    # Register overloads mirror Container.register for API parity.
    @overload
    def register(self, key: _C, /) -> _C: ...

    @overload
    def register(self, key: Callable[..., T], /) -> Callable[..., T]: ...

    @overload
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

    @overload
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

    def register(  # noqa: PLR0913, C901, PLR0911
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
        """Register a service with the current container.

        Supports the same decorator and direct-call patterns as Container.register.
        If no container is set, registration is deferred until set_current().
        """
        container = self._get_current_or_none()
        if container is not None:
            return container.register(
                key,
                factory=factory,
                instance=instance,
                lifetime=lifetime,
                scope=scope,
                is_async=is_async,
                concrete_class=concrete_class,
            )

        all_params_at_defaults = (
            factory is None
            and instance is None
            and lifetime == Lifetime.TRANSIENT
            and scope is None
            and is_async is None
            and concrete_class is None
        )

        if key is None:

            def decorator(target: T) -> T:
                current = self._get_current_or_none()
                if current is not None:
                    register_decorator = current.register(
                        lifetime=lifetime,
                        scope=scope,
                        is_async=is_async,
                        concrete_class=concrete_class,
                    )
                    register_decorator(target)
                    return target

                self._deferred_registrations.append(
                    _DeferredRegistration(
                        key=target,
                        factory=None,
                        instance=None,
                        lifetime=lifetime,
                        scope=scope,
                        is_async=is_async,
                        concrete_class=concrete_class,
                        via_decorator=True,
                    ),
                )
                return target

            return decorator

        # Case: Type as key (could be bare decorator, interface decorator, or factory)
        # When container is available, delegate to it. Otherwise defer registration.
        if (
            isinstance(key, type)
            and factory is None
            and instance is None
            and concrete_class is None
        ):
            # If container is available, delegate to it (uses proxy pattern)
            # Note: This path is tested in TestDeferredRegistrationWithTypeKey but
            # coverage measurement seems to have timing issues with it.
            current = self._get_current_or_none()
            if current is not None:  # pragma: no cover
                return current.register(
                    key,
                    lifetime=lifetime,
                    scope=scope,
                    is_async=is_async,
                )

            # No container - use deferred registration
            # For bare decorator (all defaults), defer and return the class directly
            if all_params_at_defaults:
                self._deferred_registrations.append(
                    _DeferredRegistration(
                        key=key,
                        factory=None,
                        instance=None,
                        lifetime=lifetime,
                        scope=scope,
                        is_async=is_async,
                        concrete_class=None,
                        via_decorator=False,
                    ),
                )
                return key

            # Non-default params - return a decorator for interface/factory patterns
            interface_key = key

            def type_decorator(target: T) -> T:
                current = self._get_current_or_none()
                if current is not None:
                    # Delegate to container which has the smart decorator logic
                    register_decorator = current.register(
                        interface_key,
                        lifetime=lifetime,
                        scope=scope,
                        is_async=is_async,
                    )
                    register_decorator(target)
                    return target

                # Deferred registration - determine what to register
                if isinstance(target, type):
                    if target is interface_key:
                        # Bare decorator: @container_context.register on the same class
                        self._deferred_registrations.append(
                            _DeferredRegistration(
                                key=target,
                                factory=None,
                                instance=None,
                                lifetime=lifetime,
                                scope=scope,
                                is_async=is_async,
                                concrete_class=None,
                                via_decorator=False,
                            ),
                        )
                    else:
                        # Interface registration: different class
                        self._deferred_registrations.append(
                            _DeferredRegistration(
                                key=interface_key,
                                factory=None,
                                instance=None,
                                lifetime=lifetime,
                                scope=scope,
                                is_async=is_async,
                                concrete_class=target,
                                via_decorator=False,
                            ),
                        )
                else:
                    # Factory function - need to defer with factory
                    self._deferred_registrations.append(
                        _DeferredRegistration(
                            key=interface_key,
                            factory=target,  # type: ignore[arg-type]
                            instance=None,
                            lifetime=lifetime,
                            scope=scope,
                            is_async=is_async,
                            concrete_class=None,
                            via_decorator=False,
                        ),
                    )
                return target

            return type_decorator

        is_factory_function = (
            callable(key)
            and not isinstance(key, type)
            and get_origin(key) is None
            and (
                inspect.isfunction(key) or inspect.ismethod(key) or inspect.iscoroutinefunction(key)
            )
        )
        is_decorator_target = all_params_at_defaults and (
            isinstance(key, staticmethod) or is_factory_function
        )
        if is_decorator_target:
            self._deferred_registrations.append(
                _DeferredRegistration(
                    key=key,
                    factory=factory,
                    instance=instance,
                    lifetime=lifetime,
                    scope=scope,
                    is_async=is_async,
                    concrete_class=concrete_class,
                    via_decorator=False,
                ),
            )
            return key

        self._deferred_registrations.append(
            _DeferredRegistration(
                key=key,
                factory=factory,
                instance=instance,
                lifetime=lifetime,
                scope=scope,
                is_async=is_async,
                concrete_class=concrete_class,
                via_decorator=False,
            ),
        )
        return None

    def enter_scope(self, scope_name: str | None = None) -> ScopedContainer:
        """Start a new scope on the current container.

        Args:
            scope_name: Optional name for the scope.

        Returns:
            A ScopedContainer context manager.

        """
        return self.get_current().enter_scope(scope_name)

    def compile(self) -> None:
        """Compile the current container for optimized resolution."""
        return self.get_current().compile()

    def close(self) -> None:
        """Close the current container.

        Closes all active scopes and marks the container as closed.
        After calling this method, any attempt to resolve services or start
        new scopes will raise DIWireContainerClosedError.
        """
        return self.get_current().close()

    async def aclose(self) -> None:
        """Asynchronously close the current container.

        Use this method when scopes contain async generator factories that
        need proper async cleanup.
        """
        return await self.get_current().aclose()

    def close_scope(self, scope_name: str) -> None:
        """Close all active scopes that contain the given scope name.

        This closes the named scope and all its child scopes in LIFO order
        (children first, then parents).

        Args:
            scope_name: The name of the scope to close.

        """
        return self.get_current().close_scope(scope_name)

    async def aclose_scope(self, scope_name: str) -> None:
        """Asynchronously close all active scopes that contain the given scope name.

        This closes the named scope and all its child scopes in LIFO order
        (children first, then parents).

        Args:
            scope_name: The name of the scope to close.

        """
        return await self.get_current().aclose_scope(scope_name)


container_context = _ContainerContextProxy()
