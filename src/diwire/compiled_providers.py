"""Compiled providers for optimized dependency resolution.

These providers are created at compile-time from the dependency graph,
eliminating runtime reflection and minimizing dict lookups.
"""

from __future__ import annotations

from collections.abc import Awaitable
from contextlib import AsyncExitStack
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
    """

    __slots__ = ("_instance", "_key", "_type")

    def __init__(self, t: type, key: ServiceKey) -> None:
        self._type = t
        self._key = key
        self._instance: Any = None

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        if self._instance is not None:
            return self._instance
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
    """

    __slots__ = ("_dep_providers", "_instance", "_key", "_param_names", "_type")

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

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        if self._instance is not None:
            return self._instance
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

    __slots__ = ("_factory_provider",)

    def __init__(self, factory_provider: CompiledProvider) -> None:
        self._factory_provider = factory_provider

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        factory = self._factory_provider(singletons, scoped_cache)
        return factory()


class SingletonFactoryProvider:
    """Provider for singletons created by a factory.

    Stores instance directly in the provider for fastest possible cache hit.
    """

    __slots__ = ("_factory_provider", "_instance", "_key")

    def __init__(self, key: ServiceKey, factory_provider: CompiledProvider) -> None:
        self._key = key
        self._factory_provider = factory_provider
        self._instance: Any = None

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
    ) -> Any:
        if self._instance is not None:
            return self._instance
        factory = self._factory_provider(singletons, scoped_cache)
        instance = factory()
        self._instance = instance
        singletons[self._key] = instance
        return instance


# =============================================================================
# Async Compiled Providers
# =============================================================================


class AsyncCompiledProvider(Protocol):
    """Protocol for async compiled providers."""

    def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
        async_exit_stack: AsyncExitStack | None,
    ) -> Awaitable[Any]:
        """Resolve and return an instance asynchronously."""
        ...


class AsyncFactoryProvider:
    """Async provider that uses an async factory to create instances."""

    __slots__ = ("_factory_provider",)

    def __init__(self, factory_provider: CompiledProvider | AsyncCompiledProvider) -> None:
        self._factory_provider = factory_provider

    async def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
        async_exit_stack: AsyncExitStack | None,
    ) -> Any:
        factory = self._factory_provider(singletons, scoped_cache)  # type: ignore[call-arg]
        if hasattr(factory, "__await__"):
            factory = await factory
        return await factory()  # type: ignore[operator]


class AsyncSingletonFactoryProvider:
    """Async provider for singletons created by an async factory."""

    __slots__ = ("_factory_provider", "_key")

    def __init__(
        self,
        key: ServiceKey,
        factory_provider: CompiledProvider | AsyncCompiledProvider,
    ) -> None:
        self._key = key
        self._factory_provider = factory_provider

    async def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
        async_exit_stack: AsyncExitStack | None,
    ) -> Any:
        cached = singletons.get(self._key)
        if cached is not None:
            return cached
        factory = self._factory_provider(singletons, scoped_cache)  # type: ignore[call-arg]
        if hasattr(factory, "__await__"):
            factory = await factory
        instance = await factory()  # type: ignore[operator]
        singletons[self._key] = instance
        return instance


class AsyncArgsTypeProvider:
    """Async provider for types with dependencies - resolves deps in parallel."""

    __slots__ = ("_async_dep_indices", "_dep_providers", "_param_names", "_type")

    def __init__(
        self,
        t: type,
        param_names: tuple[str, ...],
        dep_providers: tuple[CompiledProvider | AsyncCompiledProvider, ...],
        async_dep_indices: tuple[int, ...],
    ) -> None:
        self._type = t
        self._param_names = param_names
        self._dep_providers = dep_providers
        self._async_dep_indices = async_dep_indices

    async def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
        async_exit_stack: AsyncExitStack | None,
    ) -> Any:
        import asyncio

        # Resolve all dependencies, gathering async ones in parallel
        resolved: list[Any] = [None] * len(self._dep_providers)

        # First resolve sync dependencies directly
        async_tasks: list[tuple[int, Awaitable[Any]]] = []
        for i, provider in enumerate(self._dep_providers):
            if i in self._async_dep_indices:
                result = provider(singletons, scoped_cache, async_exit_stack)  # type: ignore[call-arg]
                async_tasks.append((i, result))
            else:
                resolved[i] = provider(singletons, scoped_cache)  # type: ignore[call-arg]

        # Then gather async dependencies in parallel
        if async_tasks:
            indices, awaitables = zip(*async_tasks, strict=True)
            async_results = await asyncio.gather(*awaitables)
            for idx, result in zip(indices, async_results, strict=True):
                resolved[idx] = result

        args = dict(zip(self._param_names, resolved, strict=True))
        return self._type(**args)


class AsyncSingletonArgsTypeProvider:
    """Async provider for singletons with dependencies."""

    __slots__ = ("_async_dep_indices", "_dep_providers", "_key", "_param_names", "_type")

    def __init__(
        self,
        t: type,
        key: ServiceKey,
        param_names: tuple[str, ...],
        dep_providers: tuple[CompiledProvider | AsyncCompiledProvider, ...],
        async_dep_indices: tuple[int, ...],
    ) -> None:
        self._type = t
        self._key = key
        self._param_names = param_names
        self._dep_providers = dep_providers
        self._async_dep_indices = async_dep_indices

    async def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
        async_exit_stack: AsyncExitStack | None,
    ) -> Any:
        import asyncio

        cached = singletons.get(self._key)
        if cached is not None:
            return cached

        # Resolve all dependencies, gathering async ones in parallel
        resolved: list[Any] = [None] * len(self._dep_providers)

        # First resolve sync dependencies directly
        async_tasks: list[tuple[int, Awaitable[Any]]] = []
        for i, provider in enumerate(self._dep_providers):
            if i in self._async_dep_indices:
                result = provider(singletons, scoped_cache, async_exit_stack)  # type: ignore[call-arg]
                async_tasks.append((i, result))
            else:
                resolved[i] = provider(singletons, scoped_cache)  # type: ignore[call-arg]

        # Then gather async dependencies in parallel
        if async_tasks:
            indices, awaitables = zip(*async_tasks, strict=True)
            async_results = await asyncio.gather(*awaitables)
            for idx, result in zip(indices, async_results, strict=True):
                resolved[idx] = result

        args = dict(zip(self._param_names, resolved, strict=True))
        instance = self._type(**args)
        singletons[self._key] = instance
        return instance


class SyncToAsyncProviderAdapter:
    """Adapter to use sync providers in async context."""

    __slots__ = ("_sync_provider",)

    def __init__(self, sync_provider: CompiledProvider) -> None:
        self._sync_provider = sync_provider

    async def __call__(
        self,
        singletons: dict[ServiceKey, Any],
        scoped_cache: dict[ServiceKey, Any] | None,
        async_exit_stack: AsyncExitStack | None,
    ) -> Any:
        return self._sync_provider(singletons, scoped_cache)
