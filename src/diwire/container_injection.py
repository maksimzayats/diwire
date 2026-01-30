from __future__ import annotations

import asyncio
import types
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, Generic, TypeVar

from diwire.container_helpers import _build_signature_without_injected
from diwire.dependencies import DependenciesExtractor
from diwire.service_key import ServiceKey

T = TypeVar("T", bound=Any)


class _InjectedFunction(Generic[T]):
    """A callable wrapper that resolves dependencies on each call.

    This ensures transient dependencies are created fresh on every invocation,
    while singletons are still shared as expected.

    Uses lazy initialization to support `from __future__ import annotations`,
    deferring type hint resolution until the first call.
    """

    def __init__(
        self,
        func: Callable[..., T],
        container: Any,
        dependencies_extractor: DependenciesExtractor,
        service_key: ServiceKey,
    ) -> None:
        self._func = func
        self._container = container
        self._dependencies_extractor = dependencies_extractor
        self._service_key = service_key
        self._injected_params: set[str] | None = None

        # Preserve function metadata for introspection
        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., T] = func

        # Build signature at decoration time by detecting Injected in annotations
        # This works even with string annotations from PEP 563
        self.__signature__ = _build_signature_without_injected(func)

    def _ensure_initialized(self) -> None:
        """Lazily extract dependencies on first call."""
        if self._injected_params is not None:
            return
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        self._injected_params = set(injected_deps.keys())

    def __call__(self, *args: Any, **kwargs: Any) -> T:
        """Call the wrapped function, resolving Injected dependencies fresh each time."""
        self._ensure_initialized()
        resolved = self._resolve_injected_dependencies()
        # Merge resolved dependencies with explicit kwargs (explicit kwargs take precedence)
        merged_kwargs = {**resolved, **kwargs}
        return self._func(*args, **merged_kwargs)

    def _resolve_injected_dependencies(self) -> dict[str, Any]:
        """Resolve dependencies marked with Injected."""
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        return {name: self._container.resolve(dep) for name, dep in injected_deps.items()}

    def __repr__(self) -> str:
        return f"_InjectedFunction({self._func!r})"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Descriptor protocol to bind this callable to an instance when used as a method."""
        if obj is None:
            return self
        return types.MethodType(self, obj)


class _ScopedInjectedFunction(Generic[T]):
    """A callable wrapper that creates a new scope for each call.

    Similar to _InjectedFunction, but ensures SCOPED dependencies are shared
    within a single call invocation.

    Uses lazy initialization to support `from __future__ import annotations`,
    deferring type hint resolution until the first call.
    """

    def __init__(
        self,
        func: Callable[..., T],
        container: Any,
        dependencies_extractor: DependenciesExtractor,
        service_key: ServiceKey,
        scope_name: str,
    ) -> None:
        self._func = func
        self._container = container
        self._dependencies_extractor = dependencies_extractor
        self._service_key = service_key
        self._injected_params: set[str] | None = None
        self._scope_name = scope_name

        # Preserve function metadata for introspection
        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., T] = func

        # Build signature at decoration time by detecting Injected in annotations
        # This works even with string annotations from PEP 563
        self.__signature__ = _build_signature_without_injected(func)

    def _ensure_initialized(self) -> None:
        """Lazily extract dependencies on first call."""
        if self._injected_params is not None:
            return
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        self._injected_params = set(injected_deps.keys())

    def __call__(self, *args: Any, **kwargs: Any) -> T:
        """Call the wrapped function, creating a new scope for this invocation."""
        self._ensure_initialized()
        with self._container.enter_scope(self._scope_name):
            resolved = self._resolve_injected_dependencies()
            return self._func(*args, **{**resolved, **kwargs})

    def _resolve_injected_dependencies(self) -> dict[str, Any]:
        """Resolve dependencies marked with Injected."""
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        return {name: self._container.resolve(dep) for name, dep in injected_deps.items()}

    def __repr__(self) -> str:
        return f"_ScopedInjectedFunction({self._func!r}, scope={self._scope_name!r})"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Descriptor protocol to bind this callable to an instance when used as a method."""
        if obj is None:
            return self
        return types.MethodType(self, obj)


class _AsyncInjectedFunction(Generic[T]):
    """A callable wrapper that resolves dependencies on each call for async functions.

    This ensures transient dependencies are created fresh on every invocation,
    while singletons are still shared as expected.

    Uses lazy initialization to support `from __future__ import annotations`,
    deferring type hint resolution until the first call.
    """

    def __init__(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        container: Any,
        dependencies_extractor: DependenciesExtractor,
        service_key: ServiceKey,
    ) -> None:
        self._func = func
        self._container = container
        self._dependencies_extractor = dependencies_extractor
        self._service_key = service_key
        self._injected_params: set[str] | None = None

        # Preserve function metadata for introspection
        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., Coroutine[Any, Any, T]] = func

        # Build signature at decoration time by detecting Injected in annotations
        # This works even with string annotations from PEP 563
        self.__signature__ = _build_signature_without_injected(func)

    def _ensure_initialized(self) -> None:
        """Lazily extract dependencies on first call."""
        if self._injected_params is not None:
            return
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        self._injected_params = set(injected_deps.keys())

    async def __call__(self, *args: Any, **kwargs: Any) -> T:
        """Call the wrapped async function, resolving Injected dependencies fresh each time."""
        self._ensure_initialized()
        resolved = await self._resolve_injected_dependencies()
        # Merge resolved dependencies with explicit kwargs (explicit kwargs take precedence)
        merged_kwargs = {**resolved, **kwargs}
        return await self._func(*args, **merged_kwargs)

    async def _resolve_injected_dependencies(self) -> dict[str, Any]:
        """Asynchronously resolve dependencies marked with Injected."""
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        # Resolve all dependencies in parallel
        # Wrap in create_task() so each coroutine gets its own context copy
        coros = {name: self._container.aresolve(dep) for name, dep in injected_deps.items()}
        tasks = [asyncio.create_task(coro) for coro in coros.values()]
        results = await asyncio.gather(*tasks)
        return dict(zip(coros.keys(), results, strict=True))

    def __repr__(self) -> str:
        return f"_AsyncInjectedFunction({self._func!r})"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Descriptor protocol to bind this callable to an instance when used as a method."""
        if obj is None:
            return self
        return types.MethodType(self, obj)


class _AsyncScopedInjectedFunction(Generic[T]):
    """A callable wrapper that creates a new async scope for each call.

    Similar to _AsyncInjectedFunction, but ensures SCOPED dependencies are shared
    within a single call invocation.

    Uses lazy initialization to support `from __future__ import annotations`,
    deferring type hint resolution until the first call.
    """

    def __init__(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        container: Any,
        dependencies_extractor: DependenciesExtractor,
        service_key: ServiceKey,
        scope_name: str,
    ) -> None:
        self._func = func
        self._container = container
        self._dependencies_extractor = dependencies_extractor
        self._service_key = service_key
        self._injected_params: set[str] | None = None
        self._scope_name = scope_name

        # Preserve function metadata for introspection
        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., Coroutine[Any, Any, T]] = func

        # Build signature at decoration time by detecting Injected in annotations
        # This works even with string annotations from PEP 563
        self.__signature__ = _build_signature_without_injected(func)

    def _ensure_initialized(self) -> None:
        """Lazily extract dependencies on first call."""
        if self._injected_params is not None:
            return
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        self._injected_params = set(injected_deps.keys())

    async def __call__(self, *args: Any, **kwargs: Any) -> T:
        """Call the wrapped async function, creating a new scope for this invocation."""
        self._ensure_initialized()
        async with self._container.enter_scope(self._scope_name):
            resolved = await self._resolve_injected_dependencies()
            return await self._func(*args, **{**resolved, **kwargs})

    async def _resolve_injected_dependencies(self) -> dict[str, Any]:
        """Asynchronously resolve dependencies marked with Injected."""
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        # Resolve all dependencies in parallel
        # Wrap in create_task() so each coroutine gets its own context copy
        coros = {name: self._container.aresolve(dep) for name, dep in injected_deps.items()}
        tasks = [asyncio.create_task(coro) for coro in coros.values()]
        results = await asyncio.gather(*tasks)
        return dict(zip(coros.keys(), results, strict=True))

    def __repr__(self) -> str:
        return f"_AsyncScopedInjectedFunction({self._func!r}, scope={self._scope_name!r})"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Descriptor protocol to bind this callable to an instance when used as a method."""
        if obj is None:
            return self
        return types.MethodType(self, obj)
