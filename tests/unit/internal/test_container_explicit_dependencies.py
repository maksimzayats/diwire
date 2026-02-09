from __future__ import annotations

import inspect
from collections.abc import Generator
from contextlib import contextmanager

import pytest

from diwire.container import Container
from diwire.exceptions import DIWireInvalidProviderSpecError, DIWireProviderDependencyInferenceError
from diwire.providers import ProviderDependency


class UntypedDependency:
    pass


class TypedDependency:
    pass


class Service:
    pass


class ConcreteService(Service):
    def __init__(self, dep: TypedDependency) -> None:
        self.dep = dep


def test_explicit_dependencies_bypass_inference() -> None:
    def build_service(  # type: ignore[no-untyped-def]
        raw_dependency,
        typed_dependency: TypedDependency,
    ) -> Service:
        return Service()

    signature = inspect.signature(build_service)
    dependencies = [
        ProviderDependency(
            provides=UntypedDependency,
            parameter=signature.parameters["raw_dependency"],
        ),
        ProviderDependency(
            provides=TypedDependency,
            parameter=signature.parameters["typed_dependency"],
        ),
    ]

    container = Container()
    container.register_factory(Service, factory=build_service, dependencies=dependencies)

    provider_spec = container._providers_registrations.get_by_type(Service)
    assert [dependency.parameter.name for dependency in provider_spec.dependencies] == [
        "raw_dependency",
        "typed_dependency",
    ]
    assert [dependency.provides for dependency in provider_spec.dependencies] == [
        UntypedDependency,
        TypedDependency,
    ]


def test_missing_explicit_dependencies_raises_inference_error() -> None:
    def build_service(raw_dependency) -> Service:  # type: ignore[no-untyped-def]
        return Service()

    container = Container()

    with pytest.raises(DIWireProviderDependencyInferenceError, match="raw_dependency"):
        container.register_factory(Service, factory=build_service)


def test_decorator_registration_accepts_explicit_dependencies() -> None:
    def build_service(raw_dependency) -> Service:  # type: ignore[no-untyped-def]
        return Service()

    signature = inspect.signature(build_service)
    dependencies = [
        ProviderDependency(
            provides=UntypedDependency,
            parameter=signature.parameters["raw_dependency"],
        ),
    ]

    container = Container()
    decorator = container.register_factory(Service, dependencies=dependencies)
    returned_factory = decorator(build_service)

    assert returned_factory is build_service

    provider_spec = container._providers_registrations.get_by_type(Service)
    assert [dependency.parameter.name for dependency in provider_spec.dependencies] == [
        "raw_dependency",
    ]
    assert [dependency.provides for dependency in provider_spec.dependencies] == [UntypedDependency]


def test_explicit_dependencies_reject_unknown_parameter() -> None:
    def build_service(dep: TypedDependency) -> Service:
        return Service()

    dependencies = [
        ProviderDependency(
            provides=TypedDependency,
            parameter=inspect.Parameter(
                "unknown_param",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ),
        ),
    ]

    container = Container()

    with pytest.raises(DIWireInvalidProviderSpecError, match="unknown parameter"):
        container.register_factory(Service, factory=build_service, dependencies=dependencies)


def test_explicit_dependencies_reject_duplicates() -> None:
    def build_service(dep: TypedDependency) -> Service:
        return Service()

    parameter = inspect.signature(build_service).parameters["dep"]
    dependencies = [
        ProviderDependency(provides=TypedDependency, parameter=parameter),
        ProviderDependency(provides=UntypedDependency, parameter=parameter),
    ]

    container = Container()

    with pytest.raises(DIWireInvalidProviderSpecError, match="duplicated"):
        container.register_factory(Service, factory=build_service, dependencies=dependencies)


def test_explicit_dependencies_reject_kind_mismatch() -> None:
    def build_service(dep: TypedDependency) -> Service:
        return Service()

    dependencies = [
        ProviderDependency(
            provides=TypedDependency,
            parameter=inspect.Parameter("dep", inspect.Parameter.KEYWORD_ONLY),
        ),
    ]

    container = Container()

    with pytest.raises(DIWireInvalidProviderSpecError, match="has kind"):
        container.register_factory(Service, factory=build_service, dependencies=dependencies)


def test_explicit_dependencies_for_concrete_type_are_validated() -> None:
    signature = inspect.signature(ConcreteService.__init__)
    dependencies = [
        ProviderDependency(
            provides=TypedDependency,
            parameter=signature.parameters["dep"],
        ),
    ]

    container = Container()
    container.register_concrete(Service, concrete_type=ConcreteService, dependencies=dependencies)

    provider_spec = container._providers_registrations.get_by_type(Service)
    assert [dependency.parameter.name for dependency in provider_spec.dependencies] == ["dep"]
    assert [dependency.provides for dependency in provider_spec.dependencies] == [TypedDependency]


def test_explicit_dependencies_for_generator_are_validated() -> None:
    def build_service(dep: TypedDependency) -> Generator[Service, None, None]:
        yield Service()

    signature = inspect.signature(build_service)
    dependencies = [
        ProviderDependency(
            provides=TypedDependency,
            parameter=signature.parameters["dep"],
        ),
    ]

    container = Container()
    container.register_generator(Service, generator=build_service, dependencies=dependencies)

    provider_spec = container._providers_registrations.get_by_type(Service)
    assert [dependency.parameter.name for dependency in provider_spec.dependencies] == ["dep"]
    assert [dependency.provides for dependency in provider_spec.dependencies] == [TypedDependency]


def test_explicit_dependencies_for_context_manager_are_validated() -> None:
    @contextmanager
    def build_service(dep: TypedDependency) -> Generator[Service, None, None]:
        yield Service()

    signature = inspect.signature(build_service)
    dependencies = [
        ProviderDependency(
            provides=TypedDependency,
            parameter=signature.parameters["dep"],
        ),
    ]

    container = Container()
    container.register_context_manager(
        Service,
        context_manager=build_service,
        dependencies=dependencies,
    )

    provider_spec = container._providers_registrations.get_by_type(Service)
    assert [dependency.parameter.name for dependency in provider_spec.dependencies] == ["dep"]
    assert [dependency.provides for dependency in provider_spec.dependencies] == [TypedDependency]
