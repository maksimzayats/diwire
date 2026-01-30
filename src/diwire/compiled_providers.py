"""Compiled providers for optimized dependency resolution.

These providers are created at compile-time from the dependency graph,
eliminating runtime reflection and minimizing dict lookups.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from diwire.service_key import ServiceKey


class CompiledProvider(Protocol):
    """Protocol for compiled providers."""

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        """Resolve and return an instance."""
        ...


FactoryResultHandler = Callable[[Any], Any]


class TypeProvider:
    """Provider for types with no dependencies - direct instantiation."""

    __slots__ = ("_type",)

    def __init__(self, t: type) -> None:
        self._type = t

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        return self._type()


class SingletonTypeProvider:
    """Provider for singletons with no dependencies.

    Stores instance directly in the provider for fastest possible cache hit.
    Uses double-check locking for thread safety.
    """

    __slots__ = ("_instance", "_key", "_lock", "_type")

    def __init__(self, t: type, key: ServiceKey) -> None:
        self._type = t
        self._key = key
        self._instance: Any = None
        self._lock = threading.Lock()

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        if self._instance is not None:
            return self._instance
        with self._lock:
            # Double-check: another thread may have created the instance while we waited
            if self._instance is not None:  # pragma: no cover - race timing dependent
                return self._instance  # type: ignore[unreachable]
            instance = self._type()
            self._instance = instance
            singletons[self._key] = instance
            return instance


class ArgsTypeProvider:
    """Provider for types with dependencies - uses pre-compiled callback chain."""

    __slots__ = ("_dep_providers", "_param_names", "_type")

    def __init__(
        self,
        t: type,
        param_names: tuple[str, ...],
        dep_providers: tuple[CompiledProvider, ...],
    ) -> None:
        self._type = t
        self._param_names = param_names
        self._dep_providers = dep_providers

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        args = {
            name: provider(singletons, scoped_cache)
            for name, provider in zip(self._param_names, self._dep_providers, strict=True)
        }
        return self._type(**args)


class SingletonArgsTypeProvider:
    """Provider for singletons with dependencies.

    Stores instance directly in the provider for fastest possible cache hit.
    Uses double-check locking for thread safety.
    """

    __slots__ = ("_dep_providers", "_instance", "_key", "_lock", "_param_names", "_type")

    def __init__(
        self,
        t: type,
        key: ServiceKey,
        param_names: tuple[str, ...],
        dep_providers: tuple[CompiledProvider, ...],
    ) -> None:
        self._type = t
        self._key = key
        self._param_names = param_names
        self._dep_providers = dep_providers
        self._instance: Any = None
        self._lock = threading.Lock()

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        if self._instance is not None:
            return self._instance
        with self._lock:
            # Double-check: another thread may have created the instance while we waited
            if self._instance is not None:  # pragma: no cover - race timing dependent
                return self._instance  # type: ignore[unreachable]
            args = {
                name: provider(singletons, scoped_cache)
                for name, provider in zip(self._param_names, self._dep_providers, strict=True)
            }
            instance = self._type(**args)
            self._instance = instance
            singletons[self._key] = instance
            return instance


class ScopedSingletonProvider:
    """Provider for scoped singletons with no dependencies."""

    __slots__ = ("_key", "_type")

    def __init__(self, t: type, key: ServiceKey) -> None:
        self._type = t
        self._key = key

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        if scoped_cache is not None:
            cached = scoped_cache.get(self._key)
            if cached is not None:
                return cached
            instance = self._type()
            scoped_cache[self._key] = instance
            return instance
        return self._type()


class ScopedSingletonArgsProvider:
    """Provider for scoped singletons with dependencies."""

    __slots__ = ("_dep_providers", "_key", "_param_names", "_type")

    def __init__(
        self,
        t: type,
        key: ServiceKey,
        param_names: tuple[str, ...],
        dep_providers: tuple[CompiledProvider, ...],
    ) -> None:
        self._type = t
        self._key = key
        self._param_names = param_names
        self._dep_providers = dep_providers

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        if scoped_cache is not None:
            cached = scoped_cache.get(self._key)
            if cached is not None:
                return cached
            args = {
                name: provider(singletons, scoped_cache)
                for name, provider in zip(self._param_names, self._dep_providers, strict=True)
            }
            instance = self._type(**args)
            scoped_cache[self._key] = instance
            return instance
        args = {
            name: provider(singletons, scoped_cache)
            for name, provider in zip(self._param_names, self._dep_providers, strict=True)
        }
        return self._type(**args)


class InstanceProvider:
    """Provider for pre-created instances."""

    __slots__ = ("_instance",)

    def __init__(self, instance: Any) -> None:
        self._instance = instance

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        return self._instance


class FactoryProvider:
    """Provider that uses a factory to create instances."""

    __slots__ = ("_factory_provider", "_result_handler")

    def __init__(
        self,
        factory_provider: CompiledProvider,
        result_handler: FactoryResultHandler | None = None,
    ) -> None:
        self._factory_provider = factory_provider
        self._result_handler = result_handler

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        factory = self._factory_provider(singletons, scoped_cache)
        result = factory()
        if self._result_handler is not None:
            return self._result_handler(result)
        return result


class SingletonFactoryProvider:
    """Provider for singletons created by a factory.

    Stores instance directly in the provider for fastest possible cache hit.
    Uses double-check locking for thread safety.
    """

    __slots__ = ("_factory_provider", "_instance", "_key", "_lock", "_result_handler")

    def __init__(
        self,
        key: ServiceKey,
        factory_provider: CompiledProvider,
        result_handler: FactoryResultHandler | None = None,
    ) -> None:
        self._key = key
        self._factory_provider = factory_provider
        self._instance: Any = None
        self._lock = threading.Lock()
        self._result_handler = result_handler

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        if self._instance is not None:
            return self._instance
        with self._lock:
            # Double-check: another thread may have created the instance while we waited
            if self._instance is not None:  # pragma: no cover - race timing dependent
                return self._instance  # type: ignore[unreachable]
            factory = self._factory_provider(singletons, scoped_cache)
            instance = factory()
            if self._result_handler is not None:
                instance = self._result_handler(instance)
            self._instance = instance
            singletons[self._key] = instance
            return instance
