"""Tests for PEP 563 (from __future__ import annotations) compatibility.

PEP 563 makes all annotations strings by default, which requires special handling
for detecting Injected markers at decoration time when types may not be defined yet.
"""

from __future__ import annotations

from inspect import signature
from typing import Annotated

from diwire.container import Container
from diwire.container_injection import (
    _AsyncInjectedFunction,
    _AsyncScopedInjectedFunction,
    _InjectedFunction,
    _ScopedInjectedFunction,
)
from diwire.types import Injected, Lifetime


class TestPEP563SignatureFiltering:
    """Test that signature filtering works with string annotations."""

    def test_signature_filters_injected_with_string_annotations(self) -> None:
        """Signature should exclude Injected params even with string annotations."""
        container = Container()

        # With PEP 563, this annotation becomes the string "Annotated[ServiceA, Injected()]"
        def my_func(
            value: int,
            service: Annotated[ServiceA, Injected()],
        ) -> int:
            return value

        injected = container.resolve(my_func)
        sig = signature(injected)

        # 'service' should be filtered out, 'value' should remain
        param_names = list(sig.parameters.keys())
        assert param_names == ["value"]

    def test_signature_filters_multiple_injected_params(self) -> None:
        """Multiple Injected params should all be filtered from signature."""
        container = Container()

        def my_func(
            value: int,
            service_a: Annotated[ServiceA, Injected()],
            name: str,
            service_b: Annotated[ServiceB, Injected()],
        ) -> int:
            return value

        injected = container.resolve(my_func)
        sig = signature(injected)

        param_names = list(sig.parameters.keys())
        assert param_names == ["value", "name"]

    def test_signature_empty_when_all_params_injected(self) -> None:
        """Signature should be empty when all params are Injected."""
        container = Container()

        def my_func(
            service_a: Annotated[ServiceA, Injected()],
            service_b: Annotated[ServiceB, Injected()],
        ) -> tuple[ServiceA, ServiceB]:
            return (service_a, service_b)

        injected = container.resolve(my_func)
        sig = signature(injected)

        assert len(sig.parameters) == 0


class TestPEP563ForwardReferences:
    """Test that forward references work when type is defined after decorator."""

    def test_sync_injected_with_forward_reference(self) -> None:
        """_InjectedFunction wrapper works when type is defined after the decorated function."""
        container = Container()

        # Decorate function BEFORE ForwardService is defined
        @container.resolve()
        def handler(
            value: int,
            service: Annotated[ForwardService, Injected()],
        ) -> str:
            return f"{value}: {service.name}"

        # Signature should be correct at decoration time
        sig = signature(handler)
        assert list(sig.parameters.keys()) == ["value"]

        # Call should work after ForwardService is defined
        result = handler(42)
        assert "42:" in result
        assert "ForwardService" in result

    def test_async_injected_with_forward_reference(self) -> None:
        """_AsyncInjectedFunction wrapper works with forward references."""
        container = Container()

        @container.resolve()
        async def handler(
            value: int,
            service: Annotated[ForwardService, Injected()],
        ) -> str:
            return f"{value}: {service.name}"

        # Signature should be correct at decoration time
        sig = signature(handler)
        assert list(sig.parameters.keys()) == ["value"]
        assert isinstance(handler, _AsyncInjectedFunction)

    def test_scoped_injected_with_forward_reference(self) -> None:
        """_ScopedInjectedFunction works with explicit scope and forward references."""
        container = Container()
        container.register(
            ForwardService,
            lifetime=Lifetime.SCOPED,
            scope="request",
        )

        @container.resolve(scope="request")
        def handler(
            value: int,
            service: Annotated[ForwardService, Injected()],
        ) -> str:
            return f"{value}: {service.name}"

        sig = signature(handler)
        assert list(sig.parameters.keys()) == ["value"]
        assert isinstance(handler, _ScopedInjectedFunction)

    def test_async_scoped_injected_with_forward_reference(self) -> None:
        """_AsyncScopedInjectedFunction works with explicit scope and forward references."""
        container = Container()
        container.register(
            ForwardService,
            lifetime=Lifetime.SCOPED,
            scope="request",
        )

        @container.resolve(scope="request")
        async def handler(
            value: int,
            service: Annotated[ForwardService, Injected()],
        ) -> str:
            return f"{value}: {service.name}"

        sig = signature(handler)
        assert list(sig.parameters.keys()) == ["value"]
        assert isinstance(handler, _AsyncScopedInjectedFunction)


class TestPEP563ScopeDetection:
    """Test scope detection behavior with forward references."""

    def test_explicit_scope_bypasses_type_resolution(self) -> None:
        """Explicit scope should work even when types can't be resolved."""
        container = Container()

        # Register a scoped service (type defined later)
        container.register(
            ForwardService,
            lifetime=Lifetime.SCOPED,
            scope="request",
        )

        # With explicit scope, this should work even though ForwardService
        # wasn't defined when the decorator ran
        @container.resolve(scope="request")
        def handler(service: Annotated[ForwardService, Injected()]) -> str:
            return service.name

        assert isinstance(handler, _ScopedInjectedFunction)

    def test_scope_detection_fallback_on_name_error(self) -> None:
        """When scope detection fails due to NameError, should fall back gracefully."""
        container = Container()

        # Without explicit scope and with forward reference,
        # scope detection may fail but should fall back to no scope
        @container.resolve()
        def handler(service: Annotated[ForwardService, Injected()]) -> str:
            return service.name

        # Should be regular _InjectedFunction (not _ScopedInjectedFunction) since scope
        # detection couldn't resolve the type
        assert isinstance(handler, _InjectedFunction)


class TestPEP563Resolution:
    """Test that actual dependency resolution works with PEP 563."""

    def test_sync_resolution_with_pep563(self) -> None:
        """Sync function resolution works with string annotations."""
        container = Container()

        @container.resolve()
        def handler(
            value: int,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[int, ServiceA]:
            return (value, service)

        result = handler(42)

        assert result[0] == 42
        assert isinstance(result[1], ServiceA)

    async def test_async_resolution_with_pep563(self) -> None:
        """Async function resolution works with string annotations."""
        container = Container()

        @container.resolve()
        async def handler(
            value: int,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[int, ServiceA]:
            return (value, service)

        result = await handler(42)

        assert result[0] == 42
        assert isinstance(result[1], ServiceA)

    def test_scoped_resolution_with_pep563(self) -> None:
        """Scoped resolution works with string annotations."""
        container = Container()
        container.register(ServiceA, lifetime=Lifetime.SCOPED, scope="request")

        @container.resolve(scope="request")
        def handler(
            service: Annotated[ServiceA, Injected()],
        ) -> ServiceA:
            return service

        result = handler()
        assert isinstance(result, ServiceA)

    async def test_async_scoped_resolution_with_pep563(self) -> None:
        """Async scoped resolution works with string annotations."""
        container = Container()
        container.register(ServiceA, lifetime=Lifetime.SCOPED, scope="request")

        @container.resolve(scope="request")
        async def handler(
            service: Annotated[ServiceA, Injected()],
        ) -> ServiceA:
            return service

        result = await handler()
        assert isinstance(result, ServiceA)


class TestPEP563EdgeCases:
    """Edge cases for PEP 563 compatibility."""

    def test_mixed_injected_and_regular_annotations(self) -> None:
        """Mix of Injected and regular Annotated types."""
        container = Container()

        def handler(
            value: Annotated[int, "some metadata"],
            service: Annotated[ServiceA, Injected()],
            name: Annotated[str, "more metadata"],
        ) -> int:
            return value

        injected = container.resolve(handler)
        sig = signature(injected)

        # Only 'service' should be filtered (has Injected)
        param_names = list(sig.parameters.keys())
        assert param_names == ["value", "name"]

    def test_nested_annotated_types(self) -> None:
        """Injected detection works with various annotation formats."""
        container = Container()

        def handler(
            service: Annotated[ServiceA, Injected()],
        ) -> ServiceA:
            return service

        injected = container.resolve(handler)
        sig = signature(injected)

        assert len(sig.parameters) == 0

    def test_kwargs_override_still_works(self) -> None:
        """Explicit kwargs can still override injected dependencies."""
        container = Container()

        custom_service = ServiceA()

        @container.resolve()
        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        # Override with explicit kwarg
        result = handler(service=custom_service)
        assert result is custom_service

    def test_positional_args_work_with_pep563(self) -> None:
        """Positional args work correctly with PEP 563."""
        container = Container()

        @container.resolve()
        def handler(
            a: int,
            b: str,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[int, str, ServiceA]:
            return (a, b, service)

        result = handler(1, "hello")

        assert result[0] == 1
        assert result[1] == "hello"
        assert isinstance(result[2], ServiceA)


# Service classes defined AFTER the test functions that reference them
# This simulates the real-world scenario where decorators run before types are defined


class ServiceA:
    """A simple service for testing."""


class ServiceB:
    """Another service for testing."""


class ForwardService:
    """Service defined after functions that use it as a forward reference."""

    name: str = "ForwardService"
