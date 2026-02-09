from __future__ import annotations

import inspect
from collections.abc import Generator
from contextlib import contextmanager

import pytest

from diwire.exceptions import DIWireProviderDependencyInferenceError
from diwire.providers import ProviderDependenciesExtractor, ProviderDependency


class ServiceA:
    pass


class ServiceB:
    pass


class ServiceC:
    pass


DEFAULT_SERVICE_A = ServiceA()


def test_extracts_dependencies_from_concrete_type() -> None:
    class ConcreteService:
        def __init__(self, first: ServiceA, second: ServiceB) -> None:
            self.first = first
            self.second = second

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(ConcreteService)

    assert [dependency.parameter.name for dependency in dependencies] == ["first", "second"]
    assert [dependency.provides for dependency in dependencies] == [ServiceA, ServiceB]


def test_extracts_dependencies_from_factory() -> None:
    def build_service(first: ServiceA, second: ServiceB) -> ServiceC:
        return ServiceC()

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_factory(build_service)

    assert [dependency.parameter.name for dependency in dependencies] == ["first", "second"]
    assert [dependency.provides for dependency in dependencies] == [ServiceA, ServiceB]


def test_extracts_dependencies_from_generator() -> None:
    def build_generator(dep: ServiceA) -> Generator[ServiceC, None, None]:
        yield ServiceC()

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_generator(build_generator)

    assert [dependency.parameter.name for dependency in dependencies] == ["dep"]
    assert [dependency.provides for dependency in dependencies] == [ServiceA]


def test_extracts_dependencies_from_context_manager() -> None:
    @contextmanager
    def build_context_manager(dep: ServiceA) -> Generator[ServiceC, None, None]:
        yield ServiceC()

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_context_manager(build_context_manager)

    assert [dependency.parameter.name for dependency in dependencies] == ["dep"]
    assert [dependency.provides for dependency in dependencies] == [ServiceA]


def test_includes_typed_params_with_defaults() -> None:
    def build_service(dep: ServiceA = DEFAULT_SERVICE_A) -> ServiceC:
        return ServiceC()

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_factory(build_service)

    assert [dependency.parameter.name for dependency in dependencies] == ["dep"]
    assert [dependency.provides for dependency in dependencies] == [ServiceA]


def test_required_untyped_param_raises_inference_error() -> None:
    def build_service(dep) -> ServiceC:  # type: ignore[no-untyped-def]
        return ServiceC()

    extractor = ProviderDependenciesExtractor()

    with pytest.raises(DIWireProviderDependencyInferenceError, match="dep"):
        extractor.extract_from_factory(build_service)


def test_class_without_custom_init_has_no_dependencies() -> None:
    class NoInitService:
        pass

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(NoInitService)

    assert dependencies == []


def test_validate_explicit_dependencies_for_concrete_type_uses_constructor_signature() -> None:
    class ConcreteService:
        def __init__(self, dep: ServiceA) -> None:
            self.dep = dep

    extractor = ProviderDependenciesExtractor()
    signature = inspect.signature(ConcreteService.__init__)
    dependencies = [
        ProviderDependency(
            provides=ServiceA,
            parameter=signature.parameters["dep"],
        ),
    ]

    validated = extractor.validate_explicit_for_concrete_type(ConcreteService, dependencies)

    assert [dependency.parameter.name for dependency in validated] == ["dep"]
    assert [dependency.provides for dependency in validated] == [ServiceA]


def test_validate_explicit_dependencies_for_generator_wrapper() -> None:
    def build_service(dep: ServiceA) -> Generator[ServiceC, None, None]:
        yield ServiceC()

    extractor = ProviderDependenciesExtractor()
    signature = inspect.signature(build_service)
    dependencies = [
        ProviderDependency(
            provides=ServiceA,
            parameter=signature.parameters["dep"],
        ),
    ]

    validated = extractor.validate_explicit_for_generator(build_service, dependencies)

    assert [dependency.parameter.name for dependency in validated] == ["dep"]
    assert [dependency.provides for dependency in validated] == [ServiceA]


def test_validate_explicit_dependencies_for_context_manager_wrapper() -> None:
    @contextmanager
    def build_service(dep: ServiceA) -> Generator[ServiceC, None, None]:
        yield ServiceC()

    extractor = ProviderDependenciesExtractor()
    signature = inspect.signature(build_service)
    dependencies = [
        ProviderDependency(
            provides=ServiceA,
            parameter=signature.parameters["dep"],
        ),
    ]

    validated = extractor.validate_explicit_for_context_manager(build_service, dependencies)

    assert [dependency.parameter.name for dependency in validated] == ["dep"]
    assert [dependency.provides for dependency in validated] == [ServiceA]


def test_validate_explicit_dependencies_rejects_incomplete_required_parameters() -> None:
    def build_service(first: ServiceA, second: ServiceB) -> ServiceC:
        return ServiceC()

    extractor = ProviderDependenciesExtractor()
    signature = inspect.signature(build_service)
    dependencies = [
        ProviderDependency(
            provides=ServiceA,
            parameter=signature.parameters["first"],
        ),
    ]

    with pytest.raises(
        DIWireProviderDependencyInferenceError,
        match="Missing required parameters: 'second'",
    ):
        extractor.validate_explicit_for_factory(build_service, dependencies)


def test_extract_dependencies_uses_raw_signature_annotation_when_type_hint_resolution_fails() -> (
    None
):
    def build_service(dep: ServiceA) -> ServiceC:
        return ServiceC()

    build_service.__annotations__["return"] = "MissingReturnAnnotation"
    build_service.__annotations__["dep"] = ServiceA
    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_factory(build_service)

    assert [dependency.parameter.name for dependency in dependencies] == ["dep"]
    assert [dependency.provides for dependency in dependencies] == [ServiceA]


def test_extract_dependencies_preserves_original_annotation_error_for_required_param() -> None:
    def build_service(dep) -> ServiceC:  # type: ignore[no-untyped-def]
        return ServiceC()

    build_service.__annotations__["return"] = "MissingReturnAnnotation"
    extractor = ProviderDependenciesExtractor()

    with pytest.raises(DIWireProviderDependencyInferenceError, match="Original annotation error"):
        extractor.extract_from_factory(build_service)
