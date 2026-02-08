from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from diwire.exceptions import DIWireInvalidRegistrationError
from diwire.providers import (
    ContextManagerProvider,
    FactoryProvider,
    GeneratorProvider,
    Lifetime,
    ProviderDependenciesExtractor,
    ProviderDependency,
    ProviderReturnTypeExtractor,
    ProviderSpec,
    ProvidersRegistrations,
)
from diwire.resolvers.manager import ResolversManager
from diwire.resolvers.protocol import ResolverProtocol
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
        *,
        # Define whether the container is safe for concurrent use.
        # For thread-safety and async-safety, appropriate locks will be used
        concurrency_safe: bool = True,
    ) -> None:
        self._root_scope = root_scope
        self._default_lifetime = default_lifetime
        self._concurrency_safe = concurrency_safe

        self._provider_dependencies_extractor = ProviderDependenciesExtractor()
        self._provider_return_type_extractor = ProviderReturnTypeExtractor()
        self._providers_registrations = ProvidersRegistrations()
        self._resolvers_manager = ResolversManager()

        self._root_resolver: ResolverProtocol | None = None
        if TYPE_CHECKING:
            resolver = cast("ResolverProtocol", object())
            self.resolve = resolver.resolve
            self.enter_scope = resolver.enter_scope
        else:
            self.resolve = self._resolve
            self.enter_scope = self._enter_scope

    # region Registration Methods
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
                is_async=False,
                is_any_dependency_async=False,
                needs_cleanup=False,
            ),
        )

    def register_concrete(
        self,
        provides: type[T] | None = None,
        *,
        concrete_type: type[T] | None = None,
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
        dependencies: list[ProviderDependency] | None = None,
    ) -> ConcreteTypeRegistrationDecorator[T]:
        """Register a concrete type provider in the container."""
        decorator = ConcreteTypeRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            dependencies=dependencies,
        )

        if provides is None and concrete_type is None:
            return decorator

        if provides is None:
            provides = concrete_type
        if concrete_type is None:
            concrete_type = provides

        if provides is None or concrete_type is None:
            msg = "Concrete provider registration requires either provides or concrete_type."
            raise DIWireInvalidRegistrationError(msg)

        dependencies_for_provider = self._resolve_concrete_registration_dependencies(
            concrete_type=concrete_type,
            explicit_dependencies=dependencies,
        )
        is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
            dependencies_for_provider,
        )

        self._providers_registrations.add(
            ProviderSpec(
                provides=provides,
                concrete_type=concrete_type,
                lifetime=lifetime or self._default_lifetime,
                scope=scope or self._root_scope,
                dependencies=dependencies_for_provider,
                is_async=False,
                is_any_dependency_async=is_any_dependency_async,
                needs_cleanup=False,
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
        dependencies: list[ProviderDependency] | None = None,
    ) -> FactoryRegistrationDecorator[T]:
        """Register a factory provider in the container."""
        decorator = FactoryRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            dependencies=dependencies,
        )

        if factory is None:
            return decorator

        if provides is None:
            provides = self._provider_return_type_extractor.extract_from_factory(factory=factory)

        dependencies_for_provider = self._resolve_factory_registration_dependencies(
            factory=factory,
            explicit_dependencies=dependencies,
        )
        is_async = self._provider_return_type_extractor.is_factory_async(factory)
        is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
            dependencies_for_provider,
        )

        self._providers_registrations.add(
            ProviderSpec(
                provides=provides,
                factory=factory,
                lifetime=lifetime or self._default_lifetime,
                scope=scope or self._root_scope,
                dependencies=dependencies_for_provider,
                is_async=is_async,
                is_any_dependency_async=is_any_dependency_async,
                needs_cleanup=False,
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
        dependencies: list[ProviderDependency] | None = None,
    ) -> GeneratorRegistrationDecorator[T]:
        """Register a generator provider in the container."""
        decorator = GeneratorRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            dependencies=dependencies,
        )

        if generator is None:
            return decorator

        if provides is None:
            provides = self._provider_return_type_extractor.extract_from_generator(
                generator=generator,
            )

        dependencies_for_provider = self._resolve_generator_registration_dependencies(
            generator=generator,
            explicit_dependencies=dependencies,
        )
        is_async = self._provider_return_type_extractor.is_generator_async(generator)
        is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
            dependencies_for_provider,
        )

        self._providers_registrations.add(
            ProviderSpec(
                provides=provides,
                generator=generator,
                lifetime=lifetime or self._default_lifetime,
                scope=scope or self._root_scope,
                dependencies=dependencies_for_provider,
                is_async=is_async,
                is_any_dependency_async=is_any_dependency_async,
                needs_cleanup=True,
            ),
        )

        return decorator

    def register_context_manager(
        self,
        provides: type[T] | None = None,
        *,
        context_manager: (
            Callable[..., AbstractContextManager[T]]
            | Callable[..., AbstractAsyncContextManager[T]]
            | None
        ) = None,
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
        dependencies: list[ProviderDependency] | None = None,
    ) -> ContextManagerRegistrationDecorator[T]:
        """Register a context manager provider in the container."""
        decorator = ContextManagerRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            dependencies=dependencies,
        )

        if context_manager is None:
            return decorator

        if provides is None:
            provides = self._provider_return_type_extractor.extract_from_context_manager(
                context_manager=context_manager,
            )

        dependencies_for_provider = self._resolve_context_manager_registration_dependencies(
            context_manager=context_manager,
            explicit_dependencies=dependencies,
        )
        is_async = self._provider_return_type_extractor.is_context_manager_async(context_manager)
        is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
            dependencies_for_provider,
        )

        self._providers_registrations.add(
            ProviderSpec(
                provides=provides,
                context_manager=context_manager,
                lifetime=lifetime or self._default_lifetime,
                scope=scope or self._root_scope,
                dependencies=dependencies_for_provider,
                is_async=is_async,
                is_any_dependency_async=is_any_dependency_async,
                needs_cleanup=True,
            ),
        )

        return decorator

    def _resolve_concrete_registration_dependencies(
        self,
        *,
        concrete_type: type[Any],
        explicit_dependencies: list[ProviderDependency] | None,
    ) -> list[ProviderDependency]:
        if explicit_dependencies is None:
            return self._provider_dependencies_extractor.extract_from_concrete_type(
                concrete_type=concrete_type,
            )
        return self._provider_dependencies_extractor.validate_explicit_for_concrete_type(
            concrete_type=concrete_type,
            dependencies=explicit_dependencies,
        )

    def _resolve_factory_registration_dependencies(
        self,
        *,
        factory: FactoryProvider[Any],
        explicit_dependencies: list[ProviderDependency] | None,
    ) -> list[ProviderDependency]:
        if explicit_dependencies is None:
            return self._provider_dependencies_extractor.extract_from_factory(
                factory=factory,
            )
        return self._provider_dependencies_extractor.validate_explicit_for_factory(
            factory=factory,
            dependencies=explicit_dependencies,
        )

    def _resolve_generator_registration_dependencies(
        self,
        *,
        generator: GeneratorProvider[Any],
        explicit_dependencies: list[ProviderDependency] | None,
    ) -> list[ProviderDependency]:
        if explicit_dependencies is None:
            return self._provider_dependencies_extractor.extract_from_generator(
                generator=generator,
            )
        return self._provider_dependencies_extractor.validate_explicit_for_generator(
            generator=generator,
            dependencies=explicit_dependencies,
        )

    def _resolve_context_manager_registration_dependencies(
        self,
        *,
        context_manager: ContextManagerProvider[Any],
        explicit_dependencies: list[ProviderDependency] | None,
    ) -> list[ProviderDependency]:
        if explicit_dependencies is None:
            return self._provider_dependencies_extractor.extract_from_context_manager(
                context_manager=context_manager,
            )
        return self._provider_dependencies_extractor.validate_explicit_for_context_manager(
            context_manager=context_manager,
            dependencies=explicit_dependencies,
        )

    # endregion Registration Methods

    def _resolve(self, dependency: Any) -> Any:
        if self._root_resolver is None:
            self._root_resolver = self._resolvers_manager.build_root_resolver(
                root_scope=self._root_scope,
                registrations=self._providers_registrations,
            )

        return self._root_resolver.resolve(dependency)

    def _enter_scope(self, scope: BaseScope) -> Any:
        if self._root_resolver is None:
            self._root_resolver = self._resolvers_manager.build_root_resolver(
                root_scope=self._root_scope,
                registrations=self._providers_registrations,
            )

        return self._root_resolver.enter_scope(scope)


@dataclass(slots=True, kw_only=True)
class ConcreteTypeRegistrationDecorator(Generic[T]):
    """A decorator for registering concrete type providers in the container."""

    container: Container
    scope: BaseScope | None
    lifetime: Lifetime | None
    provides: type[T] | None = None
    dependencies: list[ProviderDependency] | None = None

    def __call__(self, concrete_type: type[T]) -> type[T]:
        """Register the concrete type provider in the container."""
        self.container.register_concrete(
            provides=self.provides,
            concrete_type=concrete_type,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=self.dependencies,
        )

        return concrete_type


@dataclass(slots=True, kw_only=True)
class FactoryRegistrationDecorator(Generic[T]):
    """A decorator for registering factory providers in the container."""

    container: Container
    scope: BaseScope | None
    lifetime: Lifetime | None
    provides: type[T] | None = None
    dependencies: list[ProviderDependency] | None = None

    def __call__(self, factory: F) -> F:
        """Register the factory provider in the container."""
        self.container.register_factory(
            provides=self.provides,
            factory=factory,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=self.dependencies,
        )

        return factory


@dataclass(slots=True, kw_only=True)
class GeneratorRegistrationDecorator(Generic[T]):
    """A decorator for registering generator providers in the container."""

    container: Container
    scope: BaseScope | None
    lifetime: Lifetime | None
    provides: type[T] | None = None
    dependencies: list[ProviderDependency] | None = None

    def __call__(self, generator: F) -> F:
        """Register the generator provider in the container."""
        self.container.register_generator(
            provides=self.provides,
            generator=generator,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=self.dependencies,
        )

        return generator


@dataclass(slots=True, kw_only=True)
class ContextManagerRegistrationDecorator(Generic[T]):
    """A decorator for registering context manager providers in the container."""

    container: Container
    scope: BaseScope | None
    lifetime: Lifetime | None
    provides: type[T] | None = None
    dependencies: list[ProviderDependency] | None = None

    def __call__(self, context_manager: F) -> F:
        """Register the context manager provider in the container."""
        self.container.register_context_manager(
            provides=self.provides,
            context_manager=context_manager,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=self.dependencies,
        )

        return context_manager


def main() -> None:
    container = Container()
    container.register_instance(int, instance=42)
    container.register_factory(
        float,
        factory=lambda i: float(i) + 1,
        dependencies=[
            ProviderDependency(
                provides=int,
                parameter=inspect.Parameter(
                    name="i",
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                ),
            ),
        ],
    )


if __name__ == "__main__":
    main()
