from __future__ import annotations

from abc import ABC, abstractmethod

from diwire.container import Container
from diwire.providers import Lifetime
from diwire.scope import Scope


class DirectDependency:
    pass


class RootWithDirectDependency:
    def __init__(self, dependency: DirectDependency) -> None:
        self.dependency = dependency


class NestedDependency:
    pass


class IntermediateDependency:
    def __init__(self, dependency: NestedDependency) -> None:
        self.dependency = dependency


class RootWithNestedDependencies:
    def __init__(self, dependency: IntermediateDependency) -> None:
        self.dependency = dependency


class ScopedDependency:
    pass


class RootWithScopedDependency:
    def __init__(self, dependency: ScopedDependency) -> None:
        self.dependency = dependency


class AbstractDependency(ABC):
    @abstractmethod
    def run(self) -> None:
        """Run the dependency."""


class ValidDependency:
    pass


class RootWithMixedDependencies:
    def __init__(
        self,
        abstract_dependency: AbstractDependency,
        valid_dependency: ValidDependency,
    ) -> None:
        self.abstract_dependency = abstract_dependency
        self.valid_dependency = valid_dependency


class DecoratorDependency:
    pass


class DecoratorService:
    def __init__(self, dependency: DecoratorDependency) -> None:
        self.dependency = dependency


class ResolveDependency:
    pass


class ResolveRoot:
    def __init__(self, dependency: ResolveDependency) -> None:
        self.dependency = dependency


class ExistingDependency:
    pass


class RootWithExistingDependency:
    def __init__(self, dependency: ExistingDependency) -> None:
        self.dependency = dependency


def test_container_default_autoregisters_dependencies_during_registration() -> None:
    container = Container(autoregister_dependencies=True)

    container.register_concrete(concrete_type=RootWithDirectDependency)

    dependency_spec = container._providers_registrations.find_by_type(DirectDependency)
    assert dependency_spec is not None
    assert dependency_spec.concrete_type is DirectDependency


def test_registration_override_can_disable_dependency_autoregistration() -> None:
    container = Container(autoregister_dependencies=True)

    container.register_concrete(
        concrete_type=RootWithDirectDependency,
        autoregister_dependencies=False,
    )

    assert container._providers_registrations.find_by_type(DirectDependency) is None


def test_registration_override_can_enable_dependency_autoregistration() -> None:
    container = Container(autoregister_dependencies=False)

    container.register_concrete(
        concrete_type=RootWithDirectDependency,
        autoregister_dependencies=True,
    )

    assert container._providers_registrations.find_by_type(DirectDependency) is not None


def test_dependency_autoregistration_is_recursive() -> None:
    container = Container(autoregister_dependencies=True)

    container.register_concrete(concrete_type=RootWithNestedDependencies)

    assert container._providers_registrations.find_by_type(IntermediateDependency) is not None
    assert container._providers_registrations.find_by_type(NestedDependency) is not None


def test_dependency_autoregistration_skips_already_registered_dependency() -> None:
    container = Container(autoregister_dependencies=True)
    container.register_concrete(concrete_type=ExistingDependency)
    existing_spec = container._providers_registrations.get_by_type(ExistingDependency)

    container.register_concrete(concrete_type=RootWithExistingDependency)

    assert container._providers_registrations.get_by_type(ExistingDependency) is existing_spec


def test_dependency_autoregistration_uses_parent_scope_and_lifetime() -> None:
    container = Container()

    container.register_concrete(
        concrete_type=RootWithScopedDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
        autoregister_dependencies=True,
    )

    dependency_spec = container._providers_registrations.get_by_type(ScopedDependency)
    assert dependency_spec.scope is Scope.REQUEST
    assert dependency_spec.lifetime is Lifetime.SCOPED


def test_dependency_autoregistration_ignores_registration_failures_and_continues() -> None:
    container = Container(autoregister_dependencies=True)

    container.register_concrete(concrete_type=RootWithMixedDependencies)

    assert container._providers_registrations.find_by_type(AbstractDependency) is None
    assert container._providers_registrations.find_by_type(ValidDependency) is not None


def test_factory_decorator_can_autoregister_dependencies() -> None:
    container = Container()

    @container.register_factory(DecoratorService, autoregister_dependencies=True)
    def build_service(dependency: DecoratorDependency) -> DecoratorService:
        return DecoratorService(dependency=dependency)

    assert build_service is not None
    dependency_spec = container._providers_registrations.find_by_type(DecoratorDependency)
    assert dependency_spec is not None
    assert dependency_spec.concrete_type is DecoratorDependency


def test_resolve_autoregistration_integration_registers_dependency_chain() -> None:
    container = Container(
        autoregister=True,
        autoregister_dependencies=True,
    )

    resolved = container.resolve(ResolveRoot)

    assert isinstance(resolved, ResolveRoot)
    assert isinstance(resolved.dependency, ResolveDependency)
    assert container._providers_registrations.find_by_type(ResolveDependency) is not None
