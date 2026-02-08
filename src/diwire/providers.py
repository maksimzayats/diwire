from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass, field
from enum import Enum, auto
from inspect import Parameter
from typing import Any, Awaitable, Callable, TypeAlias, get_type_hints

from diwire.exceptions import DIWireInvalidProviderSpecError
from diwire.scope import BaseScope

UserDependency: TypeAlias = type[Any]
"""A dependency that been registered or trying to be resolved from the user's code."""

UserProviderObject: TypeAlias = Any
"""An object, function, or class provided by the user as a provider. Determined by ProviderKind."""

ProviderSlot: TypeAlias = int
"""A unique slot number assigned to each provider specification."""


@dataclass(kw_only=True)
class ProviderSpec:
    """A specification of a provider in the dependency injection system."""

    slot: int

    provides: UserDependency
    provider: UserProviderObject
    provider_kind: ProviderKind
    lifetime: Lifetime

    scope: BaseScope | None = None
    dependencies: list[_ProviderDependency] = field(default_factory=list)


class ProviderKind(Enum):
    """Defines the kind of provider used to supply a dependency."""

    VALUE = auto()
    """
    A simple value, e.g., an integer, string, or object instance.
    Usage in provider: `return value`
    """

    CALL = auto()
    """
    A callable that returns a value when invoked. Could be a function or a class constructor.
    Usage in provider: `return callable(**dependencies)`
    """
    ASYNC_CALL = auto()
    """
    An asynchronous callable that returns a value when awaited.
    Usage in provider: `return await async_callable(**dependencies)`
    """

    GENERATOR = auto()
    """
    A generator callable that yields a value.
    Usage in provider:
    ```
    gen = generator_function(**dependencies)
    resource = next(gen)
    scope_context.open_resources.append(OpenGeneratorResource(gen))
    return resource
    ```
    """
    ASYNC_GENERATOR = auto()
    """
    An asynchronous generator callable that yields a value.
    Usage in provider:
    ```
    agen = async_generator_function(**dependencies)
    resource = await anext(agen)
    scope_context.open_resources.append(OpenAsyncGeneratorResource(agen))
    return resource
    ```
    """

    CONTEXT_MANAGER = auto()
    """
    A context manager callable that provides a resource within a `with` block.
    Usage in provider:
    ```
    context_manager = context_manager_function(**dependencies)
    resource = context_manager.__enter__()
    scope_context.open_resources.append(OpenContextManagerResource(context_manager))
    return resource
    ```
    """
    ASYNC_CONTEXT_MANAGER = auto()
    """
    An asynchronous context manager callable that provides a resource within an `async with` block.
    Usage in provider:
    ```
    async_context_manager = async_context_manager_function(**dependencies)
    resource = await async_context_manager.__aenter__()
    scope_context.open_resources.append(OpenAsyncContextManagerResource(async_context_manager))
    return resource
    ```
    """


class Lifetime(Enum):
    """Defines the lifetime of a service in the container."""

    TRANSIENT = auto()
    """A new instance is created every time the service is requested."""

    SINGLETON = auto()
    """A single instance is created and shared for the lifetime of the container."""

    SCOPED = auto()
    """Instance is shared within a scope, different instances across scopes."""


@dataclass(slots=True)
class ProviderSpecExtractor:
    """Extracts ProviderSpec from user-defined provider objects."""

    root_scope: BaseScope

    # fmt: off
    _provider_dependencies_extractor: ProviderDependenciesExtractor = field(default_factory=lambda: ProviderDependenciesExtractor())  # noqa: PLW0108
    _provider_spec_introspector: _ProviderSpecIntrospector = field(default_factory=lambda: _ProviderSpecIntrospector())  # noqa: PLW0108
    # fmt: on

    _specs_extracted: int = 0

    def extract(  # noqa: PLR0913
        self,
        *,
        provider: UserProviderObject | None,
        provider_kind: ProviderKind | None,
        provides: UserDependency | None,
        scope: BaseScope,
        lifetime: Lifetime,
        dependencies: list[_ProviderDependency],
    ) -> ProviderSpec:
        """Extract a ProviderSpec from the given parameters.

        Automatically infers missing information where possible.
        """
        if provider is None and provides is None:
            msg = "Either 'provider' or 'provides' must be specified to extract a ProviderSpec."
            raise DIWireInvalidProviderSpecError(msg)

        if provider is None:
            provider = self._extract_provider_from_provides(provides)
        elif provides is None:
            provides = self._extract_provides_from_provider(provider)

        if provider_kind is None:
            provider_kind = self._extract_provider_kind_from_provider(provider)

        if scope is None:
            scope = self._extract_scope_from_provider(provider)

        if lifetime is None:
            lifetime = self._extract_lifetime_from_provider(provider, scope=scope)

        if dependencies is None:
            dependencies = self._provider_dependencies_extractor.extract_from_provider(provider)

        self._specs_extracted += 1
        return ProviderSpec(
            slot=self._specs_extracted,
            provides=provides,
            provider=provider,
            provider_kind=provider_kind,
            lifetime=lifetime,
            scope=scope,
            dependencies=dependencies,
        )

    def _extract_provider_from_provides(self, provides: UserDependency) -> UserProviderObject:
        return provides

    def _extract_provides_from_provider(self, provider: UserProviderObject) -> UserDependency:
        if not isinstance(provider, type):
            # instance handling
            return type(provider)

        return provider

    def _extract_provider_kind_from_provider(self, provider: UserProviderObject) -> ProviderKind:
        if not isinstance(provider, type):
            # instance handling
            return ProviderKind.VALUE

        return ProviderKind.CALL

    def _extract_lifetime_from_provider(
        self,
        provider: UserProviderObject,
        scope: BaseScope | None = None,
    ) -> Lifetime | None:
        if not isinstance(provider, type):
            # instance handling
            return Lifetime.SINGLETON

        if scope is not None:
            return Lifetime.SCOPED

        msg = "Cannot determine lifetime from provider without scope"
        raise DIWireInvalidProviderSpecError(msg)

    def _extract_scope_from_provider(self, provider: UserProviderObject) -> BaseScope | None:
        if not isinstance(provider, type):
            # instance handling
            return None

        msg = "Scope must be explicitly provided for class/function providers"
        raise DIWireInvalidProviderSpecError(msg)


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

    def extract_from_provider(
        self,
        concrete_type: type[Any] | None = None,
        factory: Callable[..., Any] | Callable[..., Awaitable[Any]] | None = None,
        # provider: UserProviderObject,
    ) -> list[_ProviderDependency]:
        """Extract dependencies from the given provider object."""

        if not isinstance(provider, type):
            # instance handling
            return []

        target_for_hints: Any = provider
        signature_target: Any = provider
        bound_names: set[str] = set()

        if isinstance(provider, functools.partial):
            target_for_hints = provider.func
            signature_target = provider
            bound = inspect.signature(provider.func).bind_partial(
                *provider.args,
                **(provider.keywords or {}),
            )
            bound_names = set(bound.arguments.keys())
        elif inspect.isclass(provider):
            target_for_hints = provider.__init__
            signature_target = provider
        elif (
            not inspect.isfunction(provider)
            and not inspect.ismethod(provider)
            and not inspect.isbuiltin(provider)
            and callable(provider)
        ):
            target_for_hints = provider.__call__
            signature_target = provider.__call__

        type_hints = get_type_hints(target_for_hints, include_extras=True)
        sig = inspect.signature(signature_target)
        dependencies: list[_ProviderDependency] = []

        for dep_name, dep_type in type_hints.items():
            if dep_name == "return" or dep_name in bound_names:
                continue
            param = sig.parameters.get(dep_name)
            if param is None:
                continue
            dependencies.append(
                _ProviderDependency(
                    provides=dep_type,
                    parameter=param,
                ),
            )

        return dependencies


@dataclass(slots=True)
class _ProviderDependency:
    provides: UserDependency
    parameter: Parameter


@dataclass(slots=True)
class _ProviderSpecIntrospector:
    pass
