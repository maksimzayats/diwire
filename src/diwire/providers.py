from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass, field
from enum import Enum, auto
from inspect import Parameter
from typing import Any, ClassVar, TypeAlias, TypeVar

from diwire.scope import BaseScope

T = TypeVar("T")

UserDependency: TypeAlias = Any
"""A dependency that been registered or trying to be resolved from the user's code."""

UserProviderObject: TypeAlias = Any
"""An object, function, or class provided by the user as a provider. Determined by ProviderKind."""

ProviderSlot: TypeAlias = int
"""A unique slot number assigned to each provider specification."""

ConcreteTypeProvider: TypeAlias = type[T]
"""A concrete type that can be instantiated to produce a dependency."""

FactoryProvider: TypeAlias = Callable[..., T] | Callable[..., Awaitable[T]]
"""A factory function or asynchronous function that produces a dependency."""

GeneratorProvider: TypeAlias = (
    Callable[..., Generator[T, None, None]] | Callable[..., AsyncGenerator[T, None]]
)
"""A generator function or asynchronous generator function that yields a dependency."""

ContextManagerProvider: TypeAlias = (
    Callable[..., AbstractContextManager[T]] | Callable[..., AbstractAsyncContextManager[T]]
)


@dataclass(kw_only=True)
class ProviderSpec:
    """A specification of a provider in the dependency injection system."""

    SLOT_COUNTER: ClassVar[ProviderSlot] = 0

    provides: UserDependency
    """The dependency type that this provider supplies."""

    instance: UserDependency | None = None
    """An optional instance of the provided dependency, if applicable."""
    concrete_type: ConcreteTypeProvider[Any] | None = None
    """An optional concrete type of the provided dependency, if applicable."""
    factory: FactoryProvider[Any] | None = None
    """An optional factory function to create the provided dependency, if applicable."""
    generator: GeneratorProvider[Any] | None = None
    """An optional generator function to yield the provided dependency, if applicable."""
    context_manager: ContextManagerProvider[Any] | None = None
    """An optional context manager function to manage the provided dependency, if applicable."""
    dependencies: list[ProviderDependency] = field(default_factory=list)
    """A list of dependencies required by this provider."""

    lifetime: Lifetime | None = None
    """The lifetime of the provided dependency. Could be none in case of instance providers."""
    scope: BaseScope
    """The scope in which the provided dependency is valid."""

    slot: ProviderSlot = field(init=False)
    """A unique slot number assigned to this provider specification."""

    def __post_init__(self) -> None:
        self.__class__.SLOT_COUNTER += 1
        self.slot = self.SLOT_COUNTER

    @property
    def is_async(self) -> bool:
        """Indicates whether the provider is asynchronous in nature."""
        if self.factory is not None:
            return inspect.iscoroutinefunction(self.factory)
        if self.generator is not None:
            return inspect.isasyncgenfunction(self.generator)
        if self.context_manager is not None:
            # TODO(Maksim): make sure it work with proper testing
            return hasattr(self.context_manager, "__aenter__")

        return False


class Lifetime(Enum):
    """Defines the lifetime of a service in the container."""

    TRANSIENT = auto()
    """A new instance is created every time the service is requested."""

    SINGLETON = auto()
    """A single instance is created and shared for the lifetime of the container."""

    SCOPED = auto()
    """Instance is shared within a scope, different instances across scopes."""


class ProvidersRegistrations:
    """Holds all provider specifications registered in the container."""

    def __init__(self) -> None:
        self._registrations_by_type: dict[UserDependency, ProviderSpec] = {}
        self._registrations_by_slot: dict[int, ProviderSpec] = {}

    def add(self, spec: ProviderSpec) -> None:
        """Add a new provider specification to the registrations."""
        self._registrations_by_type[spec.provides] = spec
        self._registrations_by_slot[spec.slot] = spec

    def get_by_type(self, dep_type: UserDependency) -> ProviderSpec:
        """Get a provider specification by the type of dependency it provides."""
        return self._registrations_by_type[dep_type]

    def get_by_slot(self, slot: int) -> ProviderSpec:
        """Get a provider specification by its unique slot number."""
        return self._registrations_by_slot[slot]

    def get_by_scope(self, scope: BaseScope | None) -> list[ProviderSpec]:
        """Get all provider specifications registered for a specific scope."""
        return [spec for spec in self._registrations_by_type.values() if spec.scope == scope]

    def values(self) -> list[ProviderSpec]:
        """Get all provider specifications."""
        return list(self._registrations_by_type.values())

    def __len__(self) -> int:
        return len(self._registrations_by_type)


@dataclass(slots=True)
class ProviderDependenciesExtractor:
    """Extracts dependencies from user-defined provider objects."""

    def extract_from_concrete_type(
        self,
        concrete_type: ConcreteTypeProvider[Any],
    ) -> list[ProviderDependency]:
        """Extract dependencies from a concrete type-based provider."""
        return []

    def extract_from_factory(
        self,
        factory: FactoryProvider[Any],
    ) -> list[ProviderDependency]:
        """Extract dependencies from a factory-based provider."""
        return []

    def extract_from_generator(
        self,
        generator: GeneratorProvider[Any],
    ) -> list[ProviderDependency]:
        """Extract dependencies from a generator-based provider."""
        return []

    def extract_from_context_manager(
        self,
        context_manager: ContextManagerProvider[Any],
    ) -> list[ProviderDependency]:
        """Extract dependencies from a context manager-based provider."""
        return []


@dataclass(slots=True)
class ProviderDependency:
    """Represents a dependency required by a provider."""

    provides: UserDependency
    parameter: Parameter


@dataclass(slots=True)
class _ProviderSpecIntrospector:
    pass
