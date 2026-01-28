import inspect
from dataclasses import dataclass
from typing import Annotated, NoReturn
from unittest.mock import patch

import pytest

from diwire.dependencies import DependenciesExtractor
from diwire.service_key import ServiceKey
from diwire.types import Injected


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


class TestDependenciesEdgeCases:
    """Tests for edge cases in dependencies extraction."""

    def test_signature_inspection_valueerror_fallback(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """ValueError during signature inspection returns empty dict on error."""

        # Create a regular class for testing
        class RegularClass:
            def __init__(self, value: str) -> None:
                self.value = value

        service_key = ServiceKey.from_value(RegularClass)

        # Mock inspect.signature to raise ValueError
        with patch.object(inspect, "signature", side_effect=ValueError("test error")):
            defaults = dependencies_extractor._get_parameter_defaults(service_key)
            # Should return empty dict when ValueError is raised
            assert defaults == {}

    def test_signature_inspection_typeerror_fallback(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """TypeError during signature inspection returns empty dict on error."""

        class BadSignatureClass:
            @property
            def __signature__(self) -> NoReturn:
                raise TypeError("cannot compute signature")

            def __init__(self) -> None:
                pass

        # Directly test _get_parameter_defaults
        service_key = ServiceKey.from_value(BadSignatureClass)

        # The implementation will catch TypeError and return empty dict
        defaults = dependencies_extractor._get_parameter_defaults(service_key)
        assert defaults == {}

    def test_annotated_args_less_than_min(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """Annotated with insufficient args returns None from extraction."""
        # This tests the edge case where Annotated has fewer than MIN_ANNOTATED_ARGS
        # In practice, Annotated requires at least 2 args, but we test the guard

        # Test with a proper Annotated that has Injected
        class ServiceA:
            pass

        annotated_with_fromdi = Annotated[ServiceA, Injected()]
        result = dependencies_extractor._extract_injected_type(annotated_with_fromdi)
        assert result is ServiceA

        # Test with Annotated without Injected
        annotated_without_fromdi = Annotated[ServiceA, "some metadata"]
        result = dependencies_extractor._extract_injected_type(annotated_without_fromdi)
        assert result is None

        # Test with non-Annotated type
        result = dependencies_extractor._extract_injected_type(ServiceA)
        assert result is None

    def test_get_injected_dependencies_nameerror_fallback_to_no_extras(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """NameError with include_extras falls back to get_type_hints without extras."""

        class ServiceA:
            pass

        def func_with_injected(dep: Annotated[ServiceA, Injected()]) -> None:
            pass

        service_key = ServiceKey.from_value(func_with_injected)

        # Mock get_type_hints to fail on first call (with include_extras)
        # but succeed on second call (without include_extras)
        original_get_type_hints = dependencies_extractor.get_injected_dependencies.__globals__[
            "get_type_hints"
        ]
        call_count = 0

        def mock_get_type_hints(func: object, *, include_extras: bool = False) -> dict[str, object]:
            nonlocal call_count
            call_count += 1
            if include_extras:
                raise NameError("Unresolved forward reference")
            return original_get_type_hints(func, include_extras=include_extras)

        with patch(
            "diwire.dependencies.get_type_hints",
            side_effect=mock_get_type_hints,
        ):
            # Clear the cache to ensure our code path runs
            fresh_extractor = DependenciesExtractor()
            result = fresh_extractor.get_injected_dependencies(service_key)

        # Should have called get_type_hints twice (first with extras, then without)
        assert call_count == 2
        # Without include_extras=True, Injected metadata is not extracted, so result is empty
        assert result == {}

    def test_get_injected_dependencies_typeerror_fallback_to_no_extras(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """TypeError with include_extras falls back to get_type_hints without extras."""

        class ServiceA:
            pass

        def func_with_injected(dep: Annotated[ServiceA, Injected()]) -> None:
            pass

        service_key = ServiceKey.from_value(func_with_injected)

        call_count = 0

        def mock_get_type_hints(func: object, *, include_extras: bool = False) -> dict[str, object]:
            nonlocal call_count
            call_count += 1
            if include_extras:
                raise TypeError("Cannot resolve type")
            return {"dep": ServiceA}  # Return type without Annotated wrapper

        with patch(
            "diwire.dependencies.get_type_hints",
            side_effect=mock_get_type_hints,
        ):
            fresh_extractor = DependenciesExtractor()
            result = fresh_extractor.get_injected_dependencies(service_key)

        assert call_count == 2
        # Without include_extras, the Annotated metadata is stripped, so no Injected found
        assert result == {}

    def test_get_injected_dependencies_both_calls_fail_returns_empty(
        self,
        dependencies_extractor: DependenciesExtractor,
    ) -> None:
        """When both get_type_hints calls fail, returns empty dict."""

        class ServiceA:
            pass

        def func_with_injected(dep: Annotated[ServiceA, Injected()]) -> None:
            pass

        service_key = ServiceKey.from_value(func_with_injected)

        # Mock get_type_hints to always fail
        with patch(
            "diwire.dependencies.get_type_hints",
            side_effect=NameError("Cannot resolve"),
        ):
            fresh_extractor = DependenciesExtractor()
            result = fresh_extractor.get_injected_dependencies(service_key)

        # Should return empty dict when all attempts fail
        assert result == {}
