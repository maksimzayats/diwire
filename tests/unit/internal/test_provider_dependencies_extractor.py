from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import pytest

from diwire.exceptions import DIWireProviderDependencyInferenceError
from diwire.providers import ProviderDependenciesExtractor


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
