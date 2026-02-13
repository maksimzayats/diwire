from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from types import ModuleType
from typing import Any, NamedTuple, cast

import attrs
import msgspec
import pytest

from diwire._internal.providers import ProviderDependenciesExtractor, ProviderDependency
from diwire.exceptions import DIWireProviderDependencyInferenceError


class ServiceA:
    pass


class ServiceB:
    pass


class ServiceC:
    pass


DEFAULT_SERVICE_A = ServiceA()

pydantic_v1: ModuleType | None = None
if sys.version_info < (3, 14):
    try:
        pydantic_v1 = importlib.import_module("pydantic.v1")
    except ImportError:
        pydantic_v1 = None


def _assert_dependencies(
    dependencies: list[ProviderDependency],
    *,
    expected_names: list[str],
    expected_types: list[type[object]],
) -> None:
    assert [dependency.parameter.name for dependency in dependencies] == expected_names
    assert [dependency.provides for dependency in dependencies] == expected_types


def test_extracts_dependencies_from_concrete_type() -> None:
    class ConcreteService:
        def __init__(self, first: ServiceA, second: ServiceB) -> None:
            self.first = first
            self.second = second

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(ConcreteService)

    _assert_dependencies(
        dependencies,
        expected_names=["first", "second"],
        expected_types=[ServiceA, ServiceB],
    )


def test_extracts_dependencies_from_dataclass_concrete_type() -> None:
    @dataclass
    class ConcreteService:
        first: ServiceA
        second: ServiceB

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(ConcreteService)

    _assert_dependencies(
        dependencies,
        expected_names=["first", "second"],
        expected_types=[ServiceA, ServiceB],
    )


def test_extracts_dependencies_from_namedtuple_class_concrete_type() -> None:
    class ConcreteService(NamedTuple):
        first: ServiceA
        second: ServiceB

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(ConcreteService)

    _assert_dependencies(
        dependencies,
        expected_names=["first", "second"],
        expected_types=[ServiceA, ServiceB],
    )


def test_extracts_dependencies_from_namedtuple_functional_concrete_type() -> None:
    # Ruff UP014 prefers class syntax, but this test intentionally exercises functional syntax.
    ConcreteService = NamedTuple(  # noqa: UP014
        "ConcreteService",
        [("first", ServiceA), ("second", ServiceB)],
    )
    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(ConcreteService)

    _assert_dependencies(
        dependencies,
        expected_names=["first", "second"],
        expected_types=[ServiceA, ServiceB],
    )


def test_extracts_dependencies_from_attrs_define_concrete_type() -> None:
    @attrs.define
    class ConcreteService:
        first: ServiceA
        second: ServiceB

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(ConcreteService)

    _assert_dependencies(
        dependencies,
        expected_names=["first", "second"],
        expected_types=[ServiceA, ServiceB],
    )


def test_extracts_dependencies_from_msgspec_struct_concrete_type() -> None:
    class ConcreteService(msgspec.Struct):
        first: ServiceA
        second: ServiceB

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(ConcreteService)

    _assert_dependencies(
        dependencies,
        expected_names=["first", "second"],
        expected_types=[ServiceA, ServiceB],
    )


def test_extracts_dependencies_from_msgspec_kw_only_struct_concrete_type() -> None:
    class ConcreteService(msgspec.Struct, kw_only=True):
        first: ServiceA
        second: ServiceB = ServiceB()

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(ConcreteService)

    _assert_dependencies(
        dependencies,
        expected_names=["first", "second"],
        expected_types=[ServiceA, ServiceB],
    )


def test_extracts_dependencies_from_pydantic_v2_basemodel_concrete_type() -> None:
    pydantic_module = pytest.importorskip("pydantic")
    base_model_type = cast("type[Any]", pydantic_module.BaseModel)
    config_dict = cast("Any", pydantic_module.ConfigDict)

    class ConcreteService(base_model_type):
        model_config = config_dict(arbitrary_types_allowed=True)
        first: ServiceA
        second: ServiceB

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(ConcreteService)

    _assert_dependencies(
        dependencies,
        expected_names=["first", "second"],
        expected_types=[ServiceA, ServiceB],
    )


def test_extracts_dependencies_from_pydantic_dataclass_concrete_type() -> None:
    pydantic_module = pytest.importorskip("pydantic")
    pydantic_dataclasses_module = pytest.importorskip("pydantic.dataclasses")
    config_dict = cast("Any", pydantic_module.ConfigDict)
    dataclass_decorator = cast("Any", pydantic_dataclasses_module.dataclass)

    @dataclass_decorator(config=config_dict(arbitrary_types_allowed=True))
    class ConcreteService:
        first: ServiceA
        second: ServiceB

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(ConcreteService)

    _assert_dependencies(
        dependencies,
        expected_names=["first", "second"],
        expected_types=[ServiceA, ServiceB],
    )


def test_extracts_dependencies_from_pydantic_v1_basemodel_concrete_type() -> None:
    if sys.version_info >= (3, 14):
        pytest.skip("pydantic.v1 is not supported on Python 3.14+")
    if pydantic_v1 is None:
        pytest.skip("pydantic.v1 is unavailable")

    config_type = type("Config", (), {"arbitrary_types_allowed": True})
    concrete_service_type = pydantic_v1.create_model(
        "ConcreteService",
        __config__=config_type,
        first=(ServiceA, ...),
        second=(ServiceB, ...),
    )

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(concrete_service_type)

    _assert_dependencies(
        dependencies,
        expected_names=["first", "second"],
        expected_types=[ServiceA, ServiceB],
    )


def test_extracts_dependencies_from_factory() -> None:
    def build_service(first: ServiceA, second: ServiceB) -> ServiceC:
        return ServiceC()

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_factory(build_service)

    _assert_dependencies(
        dependencies,
        expected_names=["first", "second"],
        expected_types=[ServiceA, ServiceB],
    )


def test_extracts_dependencies_from_generator() -> None:
    def build_generator(dep: ServiceA) -> Generator[ServiceC, None, None]:
        yield ServiceC()

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_generator(build_generator)

    _assert_dependencies(
        dependencies,
        expected_names=["dep"],
        expected_types=[ServiceA],
    )


def test_extracts_dependencies_from_context_manager() -> None:
    @contextmanager
    def build_context_manager(dep: ServiceA) -> Generator[ServiceC, None, None]:
        yield ServiceC()

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_context_manager(build_context_manager)

    _assert_dependencies(
        dependencies,
        expected_names=["dep"],
        expected_types=[ServiceA],
    )


def test_includes_typed_params_with_defaults() -> None:
    def build_service(dep: ServiceA = DEFAULT_SERVICE_A) -> ServiceC:
        return ServiceC()

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_factory(build_service)

    _assert_dependencies(
        dependencies,
        expected_names=["dep"],
        expected_types=[ServiceA],
    )


def test_concrete_type_skips_untyped_optional_parameter() -> None:
    class ConcreteService:
        def __init__(self, dep=DEFAULT_SERVICE_A) -> None:  # type: ignore[no-untyped-def]
            self.dep = dep

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_concrete_type(ConcreteService)

    assert dependencies == []


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
    signature = inspect.signature(ConcreteService)
    dependencies = [
        ProviderDependency(
            provides=ServiceA,
            parameter=signature.parameters["dep"],
        ),
    ]

    validated = extractor.validate_explicit_for_concrete_type(ConcreteService, dependencies)

    _assert_dependencies(
        validated,
        expected_names=["dep"],
        expected_types=[ServiceA],
    )


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

    _assert_dependencies(
        validated,
        expected_names=["dep"],
        expected_types=[ServiceA],
    )


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

    _assert_dependencies(
        validated,
        expected_names=["dep"],
        expected_types=[ServiceA],
    )


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

    _assert_dependencies(
        dependencies,
        expected_names=["dep"],
        expected_types=[ServiceA],
    )


def test_extract_dependencies_preserves_original_annotation_error_for_required_param() -> None:
    def build_service(dep) -> ServiceC:  # type: ignore[no-untyped-def]
        return ServiceC()

    build_service.__annotations__["return"] = "MissingReturnAnnotation"
    extractor = ProviderDependenciesExtractor()

    with pytest.raises(DIWireProviderDependencyInferenceError, match="Original annotation error"):
        extractor.extract_from_factory(build_service)


def test_extract_concrete_type_preserves_first_annotation_error_when_merging_callable_hints() -> (
    None
):
    class ConcreteService:
        def __init__(self, dep) -> None:  # type: ignore[no-untyped-def]
            self.dep = dep

    ConcreteService.__annotations__["broken_attr"] = "MissingClassType"
    ConcreteService.__init__.__annotations__["dep"] = "MissingInitType"
    extractor = ProviderDependenciesExtractor()

    with pytest.raises(DIWireProviderDependencyInferenceError, match="Original annotation error"):
        extractor.extract_from_concrete_type(ConcreteService)
