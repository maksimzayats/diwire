"""Tests for DependenciesExtractor class."""

import inspect
import types
from dataclasses import dataclass, field
from typing import Annotated, Generic, TypeVar, Union

from diwire.dependencies import DependenciesExtractor
from diwire.service_key import ServiceKey
from diwire.types import Injected


class ServiceA:
    pass


class ServiceB:
    def __init__(self, service_a: ServiceA) -> None:
        self.service_a = service_a


T = TypeVar("T")


class TestGetDependencies:
    def test_get_dependencies_regular_classes(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Get dependencies from regular class."""
        deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(ServiceB))

        assert deps == {"service_a": ServiceKey.from_value(ServiceA)}

    def test_get_dependencies_dataclasses(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Get dependencies from dataclass."""

        @dataclass
        class DataServiceA:
            pass

        @dataclass
        class DataServiceB:
            service_a: DataServiceA

        deps = dependencies_extractor.get_dependencies(
            ServiceKey.from_value(DataServiceB),
        )

        assert deps == {"service_a": ServiceKey.from_value(DataServiceA)}

    def test_get_dependencies_function(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Get dependencies from function."""

        def do_something(service_a: ServiceA) -> None:
            pass

        deps = dependencies_extractor.get_dependencies(
            ServiceKey.from_value(do_something),
        )

        assert deps == {"service_a": ServiceKey.from_value(ServiceA)}

    def test_get_dependencies_ignores_untyped_params(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Untyped params are ignored."""

        def handler(  # type: ignore[no-untyped-def]
            service_a: ServiceA,
            raw_value,
        ) -> None:
            pass

        deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(handler))

        assert deps == {"service_a": ServiceKey.from_value(ServiceA)}

    def test_get_dependencies_class_without_init(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Class without __init__ uses object.__init__."""

        class NoInitClass:
            pass

        deps = dependencies_extractor.get_dependencies(
            ServiceKey.from_value(NoInitClass),
        )

        assert deps == {}

    def test_get_dependencies_with_return_type(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Return type is excluded."""

        def my_func(service_a: ServiceA) -> ServiceA:
            return service_a

        deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(my_func))

        assert "return" not in deps
        assert deps == {"service_a": ServiceKey.from_value(ServiceA)}

    def test_get_dependencies_empty_init(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Class with empty __init__."""

        class EmptyInit:
            def __init__(self) -> None:
                pass

        deps = dependencies_extractor.get_dependencies(
            ServiceKey.from_value(EmptyInit),
        )

        assert deps == {}

    def test_get_dependencies_with_optional_type(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Optional type dependency."""

        def my_func(service: ServiceA | None) -> None:
            pass

        deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(my_func))

        assert "service" in deps

    def test_get_dependencies_with_union_type(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Union type dependency."""

        class ServiceC:
            pass

        def my_func(service: Union[ServiceA, ServiceC]) -> None:  # noqa: UP007
            pass

        deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(my_func))

        assert "service" in deps

    def test_get_dependencies_with_generic_type(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Generic types like List[T], Dict[K,V]."""

        def my_func(items: list[ServiceA]) -> None:
            pass

        deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(my_func))

        assert "items" in deps

    def test_get_dependencies_with_builtin_types(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Builtin types as dependencies."""

        def my_func(value: int, name: str) -> None:
            pass

        deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(my_func))

        assert deps == {
            "value": ServiceKey.from_value(int),
            "name": ServiceKey.from_value(str),
        }

    def test_get_dependencies_skips_typevar_params(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """TypeVar-bound type arguments are ignored."""

        class TypeVarService(Generic[T]):
            def __init__(self, kind: type[T], service_a: ServiceA) -> None:
                self.kind = kind
                self.service_a = service_a

        deps = dependencies_extractor.get_dependencies(
            ServiceKey.from_value(TypeVarService),
        )

        assert deps == {"service_a": ServiceKey.from_value(ServiceA)}


class TestGetInjectedDependencies:
    def test_get_injected_deps_with_injected_marker(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Get only dependencies marked with Injected."""

        def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        deps = dependencies_extractor.get_injected_dependencies(
            ServiceKey.from_value(my_func),
        )

        assert deps == {"service": ServiceKey.from_value(ServiceA)}

    def test_get_injected_deps_without_injected(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Non-Injected params are excluded."""

        def my_func(value: int) -> int:
            return value

        deps = dependencies_extractor.get_injected_dependencies(
            ServiceKey.from_value(my_func),
        )

        assert deps == {}

    def test_get_injected_deps_mixed_params(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Mix of Injected and regular params."""

        def my_func(
            value: int,
            service: Annotated[ServiceA, Injected()],
        ) -> ServiceA:
            return service

        deps = dependencies_extractor.get_injected_dependencies(
            ServiceKey.from_value(my_func),
        )

        assert deps == {"service": ServiceKey.from_value(ServiceA)}
        assert "value" not in deps

    def test_get_injected_deps_multiple_injected(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Multiple Injected parameters."""

        class ServiceC:
            pass

        def my_func(
            a: Annotated[ServiceA, Injected()],
            b: Annotated[ServiceC, Injected()],
        ) -> None:
            pass

        deps = dependencies_extractor.get_injected_dependencies(
            ServiceKey.from_value(my_func),
        )

        assert deps == {
            "a": ServiceKey.from_value(ServiceA),
            "b": ServiceKey.from_value(ServiceC),
        }

    def test_get_injected_deps_injected_not_first_metadata(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Injected not first in metadata still works."""

        def my_func(
            service: Annotated[ServiceA, "other_metadata", Injected()],
        ) -> ServiceA:
            return service

        deps = dependencies_extractor.get_injected_dependencies(
            ServiceKey.from_value(my_func),
        )

        assert deps == {"service": ServiceKey.from_value(ServiceA)}

    def test_get_injected_deps_excludes_return_type(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Return type is excluded."""

        def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        deps = dependencies_extractor.get_injected_dependencies(
            ServiceKey.from_value(my_func),
        )

        assert "return" not in deps


class TestExtractInjectedType:
    def test_extract_non_annotated_returns_none(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Non-Annotated type returns None."""
        result = dependencies_extractor._extract_injected_type(ServiceA)

        assert result is None

    def test_extract_annotated_without_injected_returns_none(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Annotated without Injected returns None."""
        annotated = Annotated[ServiceA, "some_metadata"]
        result = dependencies_extractor._extract_injected_type(annotated)

        assert result is None

    def test_extract_annotated_with_injected_returns_type(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Annotated with Injected returns inner type."""
        annotated = Annotated[ServiceA, Injected()]
        result = dependencies_extractor._extract_injected_type(annotated)

        assert result is ServiceA

    def test_extract_annotated_empty_metadata(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Annotated with no useful metadata returns None."""
        # Can't create Annotated with less than 2 args, but we can test
        # metadata that doesn't include Injected
        annotated = Annotated[ServiceA, "meta1", "meta2"]
        result = dependencies_extractor._extract_injected_type(annotated)

        assert result is None


class TestExtractTypeVarAnnotation:
    def test_extract_typevar_with_multiple_args_returns_none(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Non-singleton type arguments should return None."""
        hint = types.GenericAlias(type, (int, str))
        result = dependencies_extractor._extract_typevar_from_annotation(hint)

        assert result is None


class TestGetInitFunc:
    def test_get_init_func_with_function(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Function returns itself."""

        def my_func(service: ServiceA) -> None:
            pass

        result = dependencies_extractor._get_init_func(ServiceKey.from_value(my_func))

        assert result is my_func

    def test_get_init_func_with_class(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Class returns __init__."""

        class MyClass:
            def __init__(self, service: ServiceA) -> None:
                pass

        result = dependencies_extractor._get_init_func(ServiceKey.from_value(MyClass))

        assert result is MyClass.__init__

    def test_get_init_func_with_builtin_type(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Builtin type returns __init__ (object.__init__)."""
        result = dependencies_extractor._get_init_func(ServiceKey.from_value(int))

        # int's __init__ is a wrapper
        assert result is not None


class TestGetParameterDefaultsEdgeCases:
    """Tests for _get_parameter_defaults edge cases."""

    def test_get_parameter_defaults_with_defaults(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Function with default values returns correct mapping."""

        def func_with_defaults(a: int, b: str = "default", c: int = 10) -> None:
            pass

        result = dependencies_extractor._get_parameter_defaults(
            ServiceKey.from_value(func_with_defaults),
        )

        # a has no default, b and c have defaults
        assert result["a"] is False
        assert result["b"] is True
        assert result["c"] is True

    def test_get_parameter_defaults_lambda(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Lambda functions should work."""
        my_lambda = lambda x, y=10: x + y  # noqa: E731

        result = dependencies_extractor._get_parameter_defaults(
            ServiceKey.from_value(my_lambda),
        )

        assert "y" in result
        assert result["y"] is True  # has default

    def test_get_parameter_defaults_class_with_init(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Class with __init__ that has defaults."""

        class MyClass:
            def __init__(self, a: int, b: str = "default") -> None:
                self.a = a
                self.b = b

        result = dependencies_extractor._get_parameter_defaults(
            ServiceKey.from_value(MyClass),
        )
        # a has no default, b has default
        assert result["a"] is False
        assert result["b"] is True


class TestGetDependenciesWithDefaults:
    """Tests for get_dependencies_with_defaults method."""

    def test_get_dependencies_with_defaults_dataclass_default(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Dataclass field with default value."""

        @dataclass
        class MyClass:
            name: str = "default"

        result = dependencies_extractor.get_dependencies_with_defaults(
            ServiceKey.from_value(MyClass),
        )

        assert "name" in result
        assert result["name"].service_key == ServiceKey.from_value(str)
        assert result["name"].has_default is True

    def test_get_dependencies_with_defaults_dataclass_factory(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Dataclass field with default_factory."""

        @dataclass
        class MyClass:
            items: list[str] = field(default_factory=list)

        result = dependencies_extractor.get_dependencies_with_defaults(
            ServiceKey.from_value(MyClass),
        )

        assert "items" in result
        assert result["items"].has_default is True

    def test_get_dependencies_with_defaults_no_default(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Dataclass field without default."""

        @dataclass
        class MyClass:
            name: str

        result = dependencies_extractor.get_dependencies_with_defaults(
            ServiceKey.from_value(MyClass),
        )

        assert "name" in result
        assert result["name"].service_key == ServiceKey.from_value(str)
        assert result["name"].has_default is False

    def test_get_dependencies_with_defaults_regular_class(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Regular class __init__ with defaults."""

        class MyClass:
            def __init__(self, name: str = "default", count: int = 0) -> None:
                self.name = name
                self.count = count

        result = dependencies_extractor.get_dependencies_with_defaults(
            ServiceKey.from_value(MyClass),
        )

        assert "name" in result
        assert result["name"].has_default is True
        assert "count" in result
        assert result["count"].has_default is True

    def test_get_dependencies_with_defaults_regular_class_no_defaults(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Regular class __init__ without defaults."""

        class MyClass:
            def __init__(self, name: str, count: int) -> None:
                self.name = name
                self.count = count

        result = dependencies_extractor.get_dependencies_with_defaults(
            ServiceKey.from_value(MyClass),
        )

        assert "name" in result
        assert result["name"].has_default is False
        assert "count" in result
        assert result["count"].has_default is False

    def test_get_dependencies_with_defaults_mixed(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Mix of params with and without defaults."""

        class MyClass:
            def __init__(self, required: str, optional: int = 42) -> None:
                pass

        result = dependencies_extractor.get_dependencies_with_defaults(
            ServiceKey.from_value(MyClass),
        )

        assert result["required"].has_default is False
        assert result["optional"].has_default is True

    def test_get_dependencies_with_defaults_dataclass_mixed(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Dataclass with mixed fields."""

        @dataclass
        class MyClass:
            required: str
            with_default: int = 10
            with_factory: list[str] = field(default_factory=list)

        result = dependencies_extractor.get_dependencies_with_defaults(
            ServiceKey.from_value(MyClass),
        )

        assert result["required"].has_default is False
        assert result["with_default"].has_default is True
        assert result["with_factory"].has_default is True


def _make_generated_init_class(
    annotations: dict[str, type],
    defaults: dict[str, object] | None = None,
) -> type:
    """Create a class that simulates a generated __init__ (like pydantic BaseModel).

    The class has class-level annotations and a __signature__, but its __init__
    has no useful type hints (mimicking pydantic's generated __init__).
    """
    defaults = defaults or {}

    params = []
    for name in annotations:
        default = defaults.get(name, inspect.Parameter.empty)
        params.append(
            inspect.Parameter(
                name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=default,
            ),
        )

    cls = type("GeneratedClass", (), {"__annotations__": annotations})
    cls.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]

    # Simulate a generated __init__ that has **kwargs (no useful hints)
    def _generated_init(_self: object, **_kwargs: object) -> None:
        pass

    cls.__init__ = _generated_init  # type: ignore[misc, assignment]
    return cls


class TestGeneratedInitFallback:
    """Tests for _get_type_hints fallback with generated __init__ classes."""

    def test_generated_init_class_dependencies(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Class with generated __init__ uses class-level annotations."""
        cls = _make_generated_init_class({"service_a": ServiceA})
        deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(cls))

        assert deps == {"service_a": ServiceKey.from_value(ServiceA)}

    def test_generated_init_class_no_fields(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Class with generated __init__ and no fields."""
        cls = _make_generated_init_class({})
        deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(cls))

        assert deps == {}

    def test_generated_init_class_with_defaults(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Class with generated __init__ detects default values."""
        cls = _make_generated_init_class(
            {"required": ServiceA, "optional": int},
            defaults={"optional": 42},
        )
        result = dependencies_extractor.get_dependencies_with_defaults(
            ServiceKey.from_value(cls),
        )

        assert result["required"].has_default is False
        assert result["optional"].has_default is True

    def test_generated_init_class_multiple_deps(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Class with generated __init__ and multiple dependencies."""

        class ServiceC:
            pass

        cls = _make_generated_init_class({"a": ServiceA, "b": ServiceB, "c": ServiceC})
        deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(cls))

        assert deps == {
            "a": ServiceKey.from_value(ServiceA),
            "b": ServiceKey.from_value(ServiceB),
            "c": ServiceKey.from_value(ServiceC),
        }

    def test_regular_class_still_uses_init_hints(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Regular classes are not affected by the fallback."""

        class RegularClass:
            def __init__(self, service_a: ServiceA) -> None:
                self.service_a = service_a

        deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(RegularClass))

        assert deps == {"service_a": ServiceKey.from_value(ServiceA)}

    def test_class_with_matching_signature_and_init_hints(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Class with __signature__ that matches init hints uses init hints."""

        class MatchingClass:
            def __init__(self, service_a: ServiceA) -> None:
                self.service_a = service_a

        # Set __signature__ that matches __init__ params
        MatchingClass.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
            [inspect.Parameter("service_a", inspect.Parameter.POSITIONAL_OR_KEYWORD)],
        )

        deps = dependencies_extractor.get_dependencies(ServiceKey.from_value(MatchingClass))

        assert deps == {"service_a": ServiceKey.from_value(ServiceA)}
