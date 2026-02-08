from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from diwire.providers import (
    Lifetime,
    ProviderDependenciesExtractor,
    ProviderSpec,
    ProvidersRegistrations,
)
from diwire.scope import BaseScope, Scope

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger(__name__)


class Container:
    """A dependency injection container."""

    def __init__(
        self,
        root_scope: BaseScope = Scope.APP,
        default_lifetime: Lifetime = Lifetime.TRANSIENT,
    ) -> None:
        self._root_scope = root_scope
        self._default_lifetime = default_lifetime

        self._provider_dependencies_extractor = ProviderDependenciesExtractor()
        self._providers_registrations = ProvidersRegistrations()

    def register_instance(
        self,
        provides: type[T] | None = None,
        *,
        instance: T,
    ) -> None:
        """Register an instance provider in the container."""
        self._providers_registrations.add(
            ProviderSpec(
                provides=provides or type(instance),
                instance=instance,
                lifetime=self._default_lifetime,
                scope=self._root_scope,
            ),
        )

    def register_concrete(
        self,
        provides: type[T] | None = None,
        *,
        concrete_type: type[T] | None = None,
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
    ) -> ConcreteTypeRegistrationDecorator[T]:
        """Register a concrete type provider in the container."""
        decorator = ConcreteTypeRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
        )

        if provides is None and concrete_type is not None:
            provides = concrete_type
        elif provides is not None and concrete_type is None:
            concrete_type = provides
        elif provides is None and concrete_type is None:
            return decorator

        dependencies = self._provider_dependencies_extractor.extract_from_concrete_type(
            concrete_type=concrete_type,
        )

        self._providers_registrations.add(
            ProviderSpec(
                provides=provides,
                concrete_type=concrete_type,
                lifetime=lifetime or self._default_lifetime,
                scope=scope or self._root_scope,
                dependencies=dependencies,
            ),
        )

        return decorator

    def register_factory(
        self,
        provides: type[T] | None = None,
        *,
        factory: Callable[..., T] | Callable[..., Awaitable[T]] | None = None,
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
    ) -> FactoryRegistrationDecorator[T]:
        """Register a factory provider in the container."""
        decorator = FactoryRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
        )

        if factory is None:
            return decorator

        dependencies = self._provider_dependencies_extractor.extract_from_factory(
            factory=factory,
        )

        self._providers_registrations.add(
            ProviderSpec(
                provides=provides,
                factory=factory,
                lifetime=lifetime or self._default_lifetime,
                scope=scope or self._root_scope,
                dependencies=dependencies,
            ),
        )

        return decorator

    def register_generator(
        self,
        provides: type[T] | None = None,
        *,
        generator: (
            Callable[..., Generator[T, None, None]] | Callable[..., AsyncGenerator[T, None]] | None
        ),
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
    ) -> GeneratorRegistrationDecorator[T]:
        """Register a generator provider in the container."""
        decorator = GeneratorRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
        )

        if generator is None:
            return decorator

        dependencies = self._provider_dependencies_extractor.extract_from_generator(
            generator=generator,
        )

        self._providers_registrations.add(
            ProviderSpec(
                provides=provides,
                generator=generator,
                lifetime=lifetime or self._default_lifetime,
                scope=scope or self._root_scope,
                dependencies=dependencies,
            ),
        )

        return decorator

    def register_context_manager(
        self,
        provides: type[T] | None = None,
        *,
        context_manager: (
            Callable[..., AbstractContextManager[T]] | Callable[..., AbstractAsyncContextManager[T]]
        ),
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
    ) -> None:
        """Register a context manager provider in the container."""
        decorator = ContextManagerRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
        )

        if context_manager is None:
            return decorator

        dependencies = self._provider_dependencies_extractor.extract_from_context_manager(
            context_manager=context_manager,
        )

        self._providers_registrations.add(
            ProviderSpec(
                provides=provides,
                context_manager=context_manager,
                lifetime=lifetime or self._default_lifetime,
                scope=scope or self._root_scope,
                dependencies=dependencies,
            ),
        )

        return decorator


@dataclass(slots=True, kw_only=True)
class ConcreteTypeRegistrationDecorator(Generic[T]):
    """A decorator for registering concrete type providers in the container."""

    container: Container
    scope: BaseScope
    lifetime: Lifetime
    provides: type[T] | None = None

    def __call__(self, concrete_type: type[T]) -> type[T]:
        """Register the concrete type provider in the container."""
        self.container.register_concrete(
            provides=self.provides,
            concrete_type=concrete_type,
            scope=self.scope,
            lifetime=self.lifetime,
        )

        return concrete_type


@dataclass(slots=True, kw_only=True)
class FactoryRegistrationDecorator(Generic[T]):
    """A decorator for registering factory providers in the container."""

    container: Container
    scope: BaseScope
    lifetime: Lifetime
    provides: type[T] | None = None

    def __call__(self, factory: F) -> F:
        """Register the factory provider in the container."""
        self.container.register_factory(
            provides=self.provides,
            factory=factory,
            scope=self.scope,
            lifetime=self.lifetime,
        )

        return factory


@dataclass(slots=True, kw_only=True)
class GeneratorRegistrationDecorator(Generic[T]):
    """A decorator for registering generator providers in the container."""

    container: Container
    scope: BaseScope
    lifetime: Lifetime
    provides: type[T] | None = None

    def __call__(self, generator: F) -> F:
        """Register the generator provider in the container."""
        self.container.register_generator(
            provides=self.provides,
            generator=generator,
            scope=self.scope,
            lifetime=self.lifetime,
        )

        return generator


@dataclass(slots=True, kw_only=True)
class ContextManagerRegistrationDecorator(Generic[T]):
    """A decorator for registering context manager providers in the container."""

    container: Container
    scope: BaseScope
    lifetime: Lifetime
    provides: type[T] | None = None

    def __call__(self, context_manager: F) -> F:
        """Register the context manager provider in the container."""
        self.container.register_context_manager(
            provides=self.provides,
            context_manager=context_manager,
            scope=self.scope,
            lifetime=self.lifetime,
        )

        return context_manager


def main() -> None:
    container = Container()
    container.register_instance(int, instance=42)


if __name__ == "__main__":
    main()
