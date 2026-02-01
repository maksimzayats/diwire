"""Tests for decorator pattern support in Container.resolve()."""

from __future__ import annotations

from inspect import signature
from typing import Annotated, Any

import pytest

from diwire.container import Container
from diwire.container_injection import (
    _AsyncInjectedFunction,
    _AsyncScopedInjectedFunction,
    _InjectedFunction,
    _ScopedInjectedFunction,
)
from diwire.exceptions import DIWireServiceNotRegisteredError
from diwire.types import Injected, Lifetime


class ServiceA:
    """Test service A."""


class ServiceB:
    """Test service B."""


class TestDecoratorBasic:
    """Basic decorator pattern tests."""

    def test_decorator_with_scope_sync(self, container: Container) -> None:
        """@container.resolve(scope="test") on sync function returns _ScopedInjectedFunction."""

        @container.resolve(scope="test")
        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        assert isinstance(handler, _ScopedInjectedFunction)

    @pytest.mark.asyncio
    async def test_decorator_with_scope_async(self, container: Container) -> None:
        """@container.resolve(scope="test") on async function returns _AsyncScopedInjectedFunction."""

        @container.resolve(scope="test")
        async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        assert isinstance(handler, _AsyncScopedInjectedFunction)

    def test_decorator_without_scope_sync(self, container: Container) -> None:
        """@container.resolve() on sync function returns _InjectedFunction."""

        @container.resolve()
        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        assert isinstance(handler, _InjectedFunction)

    @pytest.mark.asyncio
    async def test_decorator_without_scope_async(self, container: Container) -> None:
        """@container.resolve() on async function returns _AsyncInjectedFunction."""

        @container.resolve()
        async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        assert isinstance(handler, _AsyncInjectedFunction)


class TestDecoratorBackwardCompatibility:
    """Ensure existing usage patterns still work."""

    def test_direct_call_still_works(self, container: Container) -> None:
        """container.resolve(my_func, scope="test") works."""

        def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        injected = container.resolve(my_func, scope="test")
        assert isinstance(injected, _ScopedInjectedFunction)

    def test_type_resolution_still_works(self, container: Container) -> None:
        """container.resolve(MyService) works."""
        result = container.resolve(ServiceA)
        assert isinstance(result, ServiceA)

    def test_direct_call_without_scope(self, container: Container) -> None:
        """container.resolve(my_func) without scope works."""

        def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        injected = container.resolve(my_func)
        assert isinstance(injected, _InjectedFunction)


class TestDecoratorMetadataPreservation:
    """Ensure function metadata is preserved through decoration."""

    def test_decorator_preserves_docstring(self, container: Container) -> None:
        """__doc__ is preserved."""

        @container.resolve(scope="test")
        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            """This is my docstring."""
            return service

        assert handler.__doc__ == "This is my docstring."

    def test_decorator_preserves_name(self, container: Container) -> None:
        """__name__ is preserved."""

        @container.resolve(scope="test")
        def my_handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        assert my_handler.__name__ == "my_handler"

    def test_decorator_signature_hides_injected_params(self, container: Container) -> None:
        """Signature shows only non-Injected params."""

        @container.resolve(scope="test")
        def handler(
            value: int,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[int, ServiceA]:
            return (value, service)

        sig = signature(handler)
        param_names = list(sig.parameters.keys())
        assert param_names == ["value"]


class TestDecoratorFunctionality:
    """Test that decorated functions resolve dependencies correctly."""

    def test_decorator_resolves_dependencies(self, container: Container) -> None:
        """Dependencies marked with Injected() are injected."""

        @container.resolve(scope="test")
        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        result = handler()
        assert isinstance(result, ServiceA)

    def test_decorator_passes_caller_args(self, container: Container) -> None:
        """Non-injected args passed by caller work."""

        @container.resolve(scope="test")
        def handler(
            value: int,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[int, ServiceA]:
            return (value, service)

        result = handler(42)
        assert result[0] == 42
        assert isinstance(result[1], ServiceA)

    def test_decorator_with_mixed_params(self, container: Container) -> None:
        """Both injected and non-injected params work together."""

        @container.resolve(scope="test")
        def handler(
            a: int,
            service_a: Annotated[ServiceA, Injected()],
            b: str,
            service_b: Annotated[ServiceB, Injected()],
        ) -> dict[str, Any]:
            return {
                "a": a,
                "b": b,
                "service_a": service_a,
                "service_b": service_b,
            }

        result = handler(1, b="hello")
        assert result["a"] == 1
        assert result["b"] == "hello"
        assert isinstance(result["service_a"], ServiceA)
        assert isinstance(result["service_b"], ServiceB)

    def test_decorator_creates_scope_per_call(self, container: Container) -> None:
        """Each call creates new scope (for scoped decorator)."""
        container.register(
            ServiceA,
            lifetime=Lifetime.SCOPED,
            scope="test",
        )

        @container.resolve(scope="test")
        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        result1 = handler()
        result2 = handler()
        # Different scopes should produce different instances
        assert result1 is not result2

    def test_decorator_scoped_shares_within_call(self, container: Container) -> None:
        """SCOPED shared within same call."""
        container.register(
            ServiceA,
            lifetime=Lifetime.SCOPED,
            scope="test",
        )

        @container.resolve(scope="test")
        def handler(
            service1: Annotated[ServiceA, Injected()],
            service2: Annotated[ServiceA, Injected()],
        ) -> tuple[ServiceA, ServiceA]:
            return (service1, service2)

        result1, result2 = handler()
        # Same scope should produce same instance
        assert result1 is result2


class TestDecoratorAsync:
    """Async functionality tests."""

    @pytest.mark.asyncio
    async def test_async_decorator_awaitable(self, container: Container) -> None:
        """Decorated async function is awaitable."""

        @container.resolve(scope="test")
        async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        result = await handler()
        assert isinstance(result, ServiceA)

    @pytest.mark.asyncio
    async def test_async_decorator_resolves_async_dependencies(self, container: Container) -> None:
        """Async factories work."""

        async def async_factory() -> ServiceA:
            return ServiceA()

        container.register(ServiceA, factory=async_factory)

        @container.resolve(scope="test")
        async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        result = await handler()
        assert isinstance(result, ServiceA)

    @pytest.mark.asyncio
    async def test_async_decorator_creates_scope_per_call(self, container: Container) -> None:
        """Each await creates new scope."""
        container.register(
            ServiceA,
            lifetime=Lifetime.SCOPED,
            scope="test",
        )

        @container.resolve(scope="test")
        async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        result1 = await handler()
        result2 = await handler()
        assert result1 is not result2


class TestDecoratorIntegration:
    """Integration tests with other patterns."""

    def test_decorator_stacking(self, container: Container) -> None:
        """Works when stacked with other decorators."""

        def logging_decorator(func):  # type: ignore[no-untyped-def]
            def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
                return func(*args, **kwargs)

            return wrapper

        @logging_decorator  # type: ignore[untyped-decorator]
        @container.resolve(scope="test")
        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        result = handler()
        assert isinstance(result, ServiceA)

    def test_decorator_with_generator_factory(self, container: Container) -> None:
        """Generator factories work with decorated functions."""
        setup_called = []

        def generator_factory() -> Any:
            setup_called.append(True)
            yield ServiceA()

        container.register(ServiceA, factory=generator_factory, scope="test")

        @container.resolve(scope="test")
        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        result = handler()
        assert isinstance(result, ServiceA)
        # Factory should have been called
        assert len(setup_called) == 1

    @pytest.mark.asyncio
    async def test_decorator_with_async_generator_factory(self, container: Container) -> None:
        """Async generator factories work with decorated async functions."""
        setup_called = []

        async def async_gen_factory() -> Any:
            setup_called.append(True)
            yield ServiceA()

        container.register(ServiceA, factory=async_gen_factory, scope="test")

        @container.resolve(scope="test")
        async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        result = await handler()
        assert isinstance(result, ServiceA)
        assert len(setup_called) == 1


class TestDecoratorEdgeCases:
    """Edge case tests."""

    def test_decorator_with_no_injected_params(self, container: Container) -> None:
        """Function with no Injected markers works."""

        @container.resolve(scope="test")
        def handler(value: int) -> int:
            return value * 2

        result = handler(21)
        assert result == 42

    def test_decorator_with_defaults(self, container: Container) -> None:
        """Non-injected parameters with defaults work correctly."""

        @container.resolve(scope="test")
        def handler(
            service: Annotated[ServiceA, Injected()],
            value: int = 10,
        ) -> tuple[int, ServiceA]:
            return (value, service)

        # With default
        result1 = handler()
        assert result1[0] == 10
        assert isinstance(result1[1], ServiceA)

        # Override default
        result2 = handler(value=20)
        assert result2[0] == 20

    def test_decorator_with_args_kwargs(self, container: Container) -> None:
        """*args and **kwargs work."""

        @container.resolve(scope="test")
        def handler(
            *args: int,
            service: Annotated[ServiceA, Injected()],
            **kwargs: str,
        ) -> dict[str, Any]:
            return {"args": args, "kwargs": kwargs, "service": service}

        result = handler(1, 2, 3, name="test")
        assert result["args"] == (1, 2, 3)
        assert result["kwargs"] == {"name": "test"}
        assert isinstance(result["service"], ServiceA)

    def test_decorator_error_unregistered_service(
        self,
        container_no_autoregister: Container,
    ) -> None:
        """Raises DIWireServiceNotRegisteredError for missing services."""

        @container_no_autoregister.resolve(scope="test")
        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        with pytest.raises(DIWireServiceNotRegisteredError):
            handler()


class TestDecoratorWithStaticmethod:
    """Test decorator with staticmethod."""

    def test_decorator_on_function_used_as_staticmethod(self, container: Container) -> None:
        """Can be used with staticmethod pattern."""

        @container.resolve(scope="test")
        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        class MyClass:
            process = staticmethod(handler)

        obj = MyClass()
        result = obj.process()
        assert isinstance(result, ServiceA)


class TestDecoratorWithoutParentheses:
    """Test that resolve can be used as decorator without parentheses when no scope needed."""

    def test_resolve_as_decorator_directly(self, container: Container) -> None:
        """@container.resolve works on a function directly."""
        # This pattern uses resolve with the function as the key directly
        injected = container.resolve

        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        result = injected(handler)
        assert isinstance(result, _InjectedFunction)
