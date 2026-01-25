from dataclasses import dataclass

import pytest

from diwire.dependencies import DependenciesExtractor
from diwire.service_key import ServiceKey


@pytest.fixture(scope="module")
def dependencies_extractor() -> DependenciesExtractor:
    return DependenciesExtractor()


def test_get_dependencies_regular_classes(dependencies_extractor: DependenciesExtractor) -> None:
    class ServiceA:
        pass

    class ServiceB:
        def __init__(self, service_a: ServiceA) -> None:
            self.service_a = service_a

    deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(ServiceB))
    assert deps == {"service_a": ServiceKey.from_value(ServiceA)}


def test_get_dependencies_dataclasses(dependencies_extractor: DependenciesExtractor) -> None:
    @dataclass
    class ServiceA:
        pass

    @dataclass
    class ServiceB:
        service_a: ServiceA

    deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(ServiceB))
    assert deps == {"service_a": ServiceKey.from_value(ServiceA)}


def test_get_dependencies_function(dependencies_extractor: DependenciesExtractor) -> None:
    class ServiceA:
        pass

    def do_something(service_a: ServiceA) -> None:
        pass

    deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(do_something))
    assert deps == {"service_a": ServiceKey.from_value(ServiceA)}


def test_get_dependencies_ignores_untyped_params(
    dependencies_extractor: DependenciesExtractor,
) -> None:
    class ServiceA:
        pass

    def handler(service_a: ServiceA, raw_value) -> None:  # type: ignore[no-untyped-def]
        pass

    deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(handler))
    assert deps == {"service_a": ServiceKey.from_value(ServiceA)}
