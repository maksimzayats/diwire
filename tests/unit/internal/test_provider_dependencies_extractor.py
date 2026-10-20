from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from types import ModuleType
from typing import Annotated, Any, ForwardRef, Literal, NamedTuple, cast

import attrs
import msgspec
import pytest
from typing_extensions import Self

from diwire import Container
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


@pytest.mark.parametrize("annotation", [ServiceA, "ServiceA", "'ServiceA'"])
def test_constructor_annotation_takes_priority_over_stored_field(annotation: Any) -> None:
    class ConcreteService:
        first: ServiceB

        def __init__(self, first: ServiceA) -> None:
            self.first = ServiceB()

    ConcreteService.__init__.__annotations__["first"] = annotation
    dependencies = ProviderDependenciesExtractor().extract_from_concrete_type(ConcreteService)
    _assert_dependencies(dependencies, expected_names=["first"], expected_types=[ServiceA])


def test_inherited_constructor_takes_priority_over_field_and_instance_call() -> None:
    class Parent:
        def __init__(self, first: ServiceA) -> None:
            assert isinstance(first, ServiceA)

    class ConcreteService(Parent):
        first: ServiceB

        def __call__(self, first: ServiceC) -> None:
            pass

    dependencies = ProviderDependenciesExtractor().extract_from_concrete_type(ConcreteService)
    _assert_dependencies(dependencies, expected_names=["first"], expected_types=[ServiceA])


def test_new_signature_takes_priority_over_init_and_fields() -> None:
    class ConcreteService:
        first: ServiceC

        def __new__(cls, first: ServiceA) -> Self:
            assert isinstance(first, ServiceA)
            return super().__new__(cls)

        def __init__(self, first: ServiceB) -> None:
            pass

    dependencies = ProviderDependenciesExtractor().extract_from_concrete_type(ConcreteService)
    _assert_dependencies(dependencies, expected_names=["first"], expected_types=[ServiceA])


def test_nearer_init_signature_takes_priority_over_inherited_new() -> None:
    class Parent:
        def __new__(cls, first: ServiceB) -> Self:
            assert isinstance(first, ServiceB)
            return super().__new__(cls)

    class ConcreteService(Parent):
        first: ServiceC

        def __init__(self, first: ServiceA) -> None:
            pass

    dependencies = ProviderDependenciesExtractor().extract_from_concrete_type(ConcreteService)
    _assert_dependencies(dependencies, expected_names=["first"], expected_types=[ServiceA])


def test_metaclass_call_signature_takes_priority_over_constructor_and_field() -> None:
    class Meta(type):
        def __call__(cls, first: ServiceA) -> object:
            return object()

    class ConcreteService(metaclass=Meta):
        first: ServiceC

        def __init__(self, first: ServiceB) -> None:
            pass

    dependencies = ProviderDependenciesExtractor().extract_from_concrete_type(ConcreteService)
    _assert_dependencies(dependencies, expected_names=["first"], expected_types=[ServiceA])


def test_synthetic_signature_keeps_its_concrete_parameter_type() -> None:
    class ConcreteService:
        first: ServiceC

        def __init__(self, first: ServiceB) -> None:
            pass

    ConcreteService.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        [inspect.Parameter("first", inspect.Parameter.KEYWORD_ONLY, annotation=ServiceA)],
    )
    dependencies = ProviderDependenciesExtractor().extract_from_concrete_type(ConcreteService)
    _assert_dependencies(dependencies, expected_names=["first"], expected_types=[ServiceA])


def test_attrs_converter_uses_input_type_instead_of_field_type() -> None:
    def convert(first: ServiceA) -> ServiceB:
        return ServiceB()

    @attrs.define
    class ConcreteService:
        first: ServiceB = attrs.field(converter=convert)

    dependencies = ProviderDependenciesExtractor().extract_from_concrete_type(ConcreteService)
    _assert_dependencies(dependencies, expected_names=["first"], expected_types=[ServiceA])


def test_pydantic_data_field_does_not_use_variadic_init_annotation() -> None:
    pydantic_module = pytest.importorskip("pydantic")
    base_model_type = cast("type[Any]", pydantic_module.BaseModel)
    config_dict = cast("Any", pydantic_module.ConfigDict)

    class ConcreteService(base_model_type):
        model_config = config_dict(arbitrary_types_allowed=True)
        data: ServiceA

    dependencies = ProviderDependenciesExtractor().extract_from_concrete_type(ConcreteService)
    _assert_dependencies(dependencies, expected_names=["data"], expected_types=[ServiceA])


@pytest.mark.parametrize("annotation", [ServiceA, "ServiceA", "'ServiceA'"])
def test_container_injects_constructor_input_before_converting_to_stored_field(
    annotation: Any,
) -> None:
    received: list[ServiceA] = []

    class ConcreteService:
        first: ServiceB

        def __init__(self, first: ServiceA) -> None:
            received.append(first)
            self.first = ServiceB()

    ConcreteService.__init__.__annotations__["first"] = annotation
    dependency = ServiceA()
    container = Container()
    container.add_instance(dependency)
    container.add(ConcreteService)
    with container as resolver:
        result = resolver.resolve(ConcreteService)
        assert received == [dependency]
        assert isinstance(result.first, ServiceB)


@pytest.mark.parametrize(
    ("signature_type", "resolved_type"),
    [
        (list["ServiceA"], list[ServiceA]),
        (dict[str, list["ServiceA"]], dict[str, list[ServiceA]]),
        (Callable[["ServiceA"], ServiceB], Callable[[ServiceA], ServiceB]),
        (ForwardRef("ServiceA"), ServiceA),
        ("ServiceA", ServiceA),
        (inspect.Parameter.empty, ServiceA),
        (list[ServiceA], list[ServiceA]),
        (Literal["value"], Literal["value"]),
        (Annotated[ServiceA, "metadata"], Annotated[ServiceA, "metadata"]),
        (None, type(None)),
    ],
)
def test_synthetic_signature_uses_resolved_types_without_replacing_forward_hints(
    signature_type: Any,
    resolved_type: Any,
) -> None:
    class ConcreteService:
        def __init__(self, first: ServiceA) -> None:
            pass

    ConcreteService.__annotations__["first"] = resolved_type
    ConcreteService.__init__.__annotations__["first"] = ServiceC
    ConcreteService.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        [inspect.Parameter("first", inspect.Parameter.KEYWORD_ONLY, annotation=signature_type)],
    )
    dependencies = ProviderDependenciesExtractor().extract_from_concrete_type(ConcreteService)
    assert dependencies[0].provides == resolved_type


@pytest.mark.skipif(sys.version_info < (3, 14), reason="inspect unwraps builtins on Python 3.14+")
@pytest.mark.parametrize("wrapped_member", ["new", "call"])
def test_wrapped_builtin_constructor_leaves_init_signature_in_control(wrapped_member: str) -> None:
    class Meta(type):
        @wraps(type.__call__)
        def __call__(cls, *args: Any, **kwargs: Any) -> Any:
            return super().__call__(*args, **kwargs)

    class ConcreteService:
        def __init__(self, first: ServiceA) -> None:
            assert isinstance(first, ServiceA)

    class WithWrappedNew(ConcreteService):
        @wraps(object.__new__)
        def __new__(cls, *args: Any, **kwargs: Any) -> Self:
            del args, kwargs
            return object.__new__(cls)

    class WithWrappedCall(ConcreteService, metaclass=Meta):
        pass

    concrete_type = WithWrappedNew if wrapped_member == "new" else WithWrappedCall
    dependencies = ProviderDependenciesExtractor().extract_from_concrete_type(concrete_type)
    _assert_dependencies(dependencies, expected_names=["first"], expected_types=[ServiceA])


def test_wrapped_constructor_keeps_explicit_method_signature() -> None:
    def original(self: object, first: ServiceB) -> None:
        pass

    @wraps(original)
    def wrapper(self: object, first: ServiceA) -> None:
        pass

    wrapper.__annotations__ = {"first": ServiceA, "return": None}
    wrapper.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        [
            inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter(
                "first", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=ServiceA
            ),
        ],
    )
    concrete_type = type("ConcreteService", (), {"__init__": wrapper})
    dependencies = ProviderDependenciesExtractor().extract_from_concrete_type(concrete_type)
    _assert_dependencies(dependencies, expected_names=["first"], expected_types=[ServiceA])


def test_concrete_signature_survives_unresolved_return_annotation() -> None:
    class ConcreteService:
        first: ServiceB

        def __init__(self, first: ServiceA) -> None:
            pass

    ConcreteService.__init__.__annotations__["first"] = ServiceA
    ConcreteService.__init__.__annotations__["return"] = "MissingReturnType"
    dependencies = ProviderDependenciesExtractor().extract_from_concrete_type(ConcreteService)
    _assert_dependencies(dependencies, expected_names=["first"], expected_types=[ServiceA])


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
