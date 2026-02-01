"""Tests for explicitly registering types that are normally ignored (primitives)."""

from typing import Annotated

import pytest

from diwire import Component, Container, Lifetime
from diwire.exceptions import DIWireMissingDependenciesError
from diwire.types import Injected


class TestPrimitiveTypesExplicitRegistration:
    """Test that explicitly registered primitive types are resolved correctly."""

    def test_registered_str_is_resolved_sync(self, container: Container) -> None:
        """Sync: registered str should be injected, not marked as missing."""
        container.register(str, instance="hello")

        class Service:
            def __init__(self, value: str) -> None:
                self.value = value

        result = container.resolve(Service)
        assert result.value == "hello"

    @pytest.mark.asyncio
    async def test_registered_str_is_resolved_async(self, container: Container) -> None:
        """Async: registered str should be injected."""
        container.register(str, instance="hello")

        class Service:
            def __init__(self, value: str) -> None:
                self.value = value

        result = await container.aresolve(Service)
        assert result.value == "hello"

    def test_registered_int_is_resolved_sync(self, container: Container) -> None:
        """Sync: registered int should be injected."""
        container.register(int, instance=42)

        class Service:
            def __init__(self, value: int) -> None:
                self.value = value

        result = container.resolve(Service)
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_registered_int_is_resolved_async(self, container: Container) -> None:
        """Async: registered int should be injected."""
        container.register(int, instance=42)

        class Service:
            def __init__(self, value: int) -> None:
                self.value = value

        result = await container.aresolve(Service)
        assert result.value == 42

    def test_registered_float_is_resolved_sync(self, container: Container) -> None:
        """Sync: registered float should be injected."""
        container.register(float, instance=3.14)

        class Service:
            def __init__(self, value: float) -> None:
                self.value = value

        result = container.resolve(Service)
        assert result.value == 3.14

    @pytest.mark.asyncio
    async def test_registered_float_is_resolved_async(self, container: Container) -> None:
        """Async: registered float should be injected."""
        container.register(float, instance=3.14)

        class Service:
            def __init__(self, value: float) -> None:
                self.value = value

        result = await container.aresolve(Service)
        assert result.value == 3.14

    def test_registered_bool_is_resolved_sync(self, container: Container) -> None:
        """Sync: registered bool should be injected."""
        container.register(bool, instance=True)

        class Service:
            def __init__(self, *, value: bool) -> None:
                self.value = value

        result = container.resolve(Service)
        assert result.value is True

    @pytest.mark.asyncio
    async def test_registered_bool_is_resolved_async(self, container: Container) -> None:
        """Async: registered bool should be injected."""
        container.register(bool, instance=True)

        class Service:
            def __init__(self, *, value: bool) -> None:
                self.value = value

        result = await container.aresolve(Service)
        assert result.value is True

    def test_registered_list_is_resolved_sync(self, container: Container) -> None:
        """Sync: registered list should be injected."""
        container.register(list, instance=[1, 2, 3])

        class Service:
            def __init__(self, value: list) -> None:  # type: ignore[type-arg]
                self.value = value

        result = container.resolve(Service)
        assert result.value == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_registered_list_is_resolved_async(self, container: Container) -> None:
        """Async: registered list should be injected."""
        container.register(list, instance=[1, 2, 3])

        class Service:
            def __init__(self, value: list) -> None:  # type: ignore[type-arg]
                self.value = value

        result = await container.aresolve(Service)
        assert result.value == [1, 2, 3]

    def test_registered_dict_is_resolved_sync(self, container: Container) -> None:
        """Sync: registered dict should be injected."""
        container.register(dict, instance={"key": "value"})

        class Service:
            def __init__(self, value: dict) -> None:  # type: ignore[type-arg]
                self.value = value

        result = container.resolve(Service)
        assert result.value == {"key": "value"}

    @pytest.mark.asyncio
    async def test_registered_dict_is_resolved_async(self, container: Container) -> None:
        """Async: registered dict should be injected."""
        container.register(dict, instance={"key": "value"})

        class Service:
            def __init__(self, value: dict) -> None:  # type: ignore[type-arg]
                self.value = value

        result = await container.aresolve(Service)
        assert result.value == {"key": "value"}

    def test_registered_set_is_resolved_sync(self, container: Container) -> None:
        """Sync: registered set should be injected."""
        container.register(set, instance={1, 2, 3})

        class Service:
            def __init__(self, value: set) -> None:  # type: ignore[type-arg]
                self.value = value

        result = container.resolve(Service)
        assert result.value == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_registered_set_is_resolved_async(self, container: Container) -> None:
        """Async: registered set should be injected."""
        container.register(set, instance={1, 2, 3})

        class Service:
            def __init__(self, value: set) -> None:  # type: ignore[type-arg]
                self.value = value

        result = await container.aresolve(Service)
        assert result.value == {1, 2, 3}

    def test_registered_tuple_is_resolved_sync(self, container: Container) -> None:
        """Sync: registered tuple should be injected."""
        container.register(tuple, instance=(1, 2, 3))

        class Service:
            def __init__(self, value: tuple) -> None:  # type: ignore[type-arg]
                self.value = value

        result = container.resolve(Service)
        assert result.value == (1, 2, 3)

    @pytest.mark.asyncio
    async def test_registered_tuple_is_resolved_async(self, container: Container) -> None:
        """Async: registered tuple should be injected."""
        container.register(tuple, instance=(1, 2, 3))

        class Service:
            def __init__(self, value: tuple) -> None:  # type: ignore[type-arg]
                self.value = value

        result = await container.aresolve(Service)
        assert result.value == (1, 2, 3)


class TestRegistrationVariations:
    """Test different registration methods for ignored types."""

    def test_factory_registration_sync(self, container: Container) -> None:
        """Sync: factory-registered primitive should work."""
        container.register(str, factory=lambda: "from factory")

        class Service:
            def __init__(self, value: str) -> None:
                self.value = value

        result = container.resolve(Service)
        assert result.value == "from factory"

    @pytest.mark.asyncio
    async def test_factory_registration_async(self, container: Container) -> None:
        """Async: factory-registered primitive should work."""
        container.register(str, factory=lambda: "from factory")

        class Service:
            def __init__(self, value: str) -> None:
                self.value = value

        result = await container.aresolve(Service)
        assert result.value == "from factory"

    def test_singleton_lifetime_sync(self, container: Container) -> None:
        """Sync: singleton primitive returns same instance."""
        call_count = 0

        def counter_factory() -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        container.register(int, factory=counter_factory, lifetime=Lifetime.SINGLETON)

        class Service:
            def __init__(self, value: int) -> None:
                self.value = value

        result1 = container.resolve(Service)
        result2 = container.resolve(Service)
        assert result1.value == result2.value == 1
        assert call_count == 1

    def test_transient_lifetime_sync(self, container: Container) -> None:
        """Sync: transient primitive creates new instances."""
        call_count = 0

        def counter_factory() -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        container.register(int, factory=counter_factory, lifetime=Lifetime.TRANSIENT)

        class Service:
            def __init__(self, value: int) -> None:
                self.value = value

        result1 = container.resolve(Service)
        result2 = container.resolve(Service)
        assert result1.value == 1
        assert result2.value == 2
        assert call_count == 2


class TestDefaultValues:
    """Test interaction between defaults and explicit registration."""

    def test_unregistered_uses_default_sync(self, container: Container) -> None:
        """Sync: unregistered ignored type with default uses the default."""

        class Service:
            def __init__(self, value: str = "default") -> None:
                self.value = value

        result = container.resolve(Service)
        assert result.value == "default"

    @pytest.mark.asyncio
    async def test_unregistered_uses_default_async(self, container: Container) -> None:
        """Async: unregistered ignored type with default uses the default."""

        class Service:
            def __init__(self, value: str = "default") -> None:
                self.value = value

        result = await container.aresolve(Service)
        assert result.value == "default"

    def test_registered_overrides_default_sync(self, container: Container) -> None:
        """Sync: registered ignored type overrides the default value."""
        container.register(str, instance="registered")

        class Service:
            def __init__(self, value: str = "default") -> None:
                self.value = value

        result = container.resolve(Service)
        assert result.value == "registered"

    @pytest.mark.asyncio
    async def test_registered_overrides_default_async(self, container: Container) -> None:
        """Async: registered ignored type overrides the default value."""
        container.register(str, instance="registered")

        class Service:
            def __init__(self, value: str = "default") -> None:
                self.value = value

        result = await container.aresolve(Service)
        assert result.value == "registered"


class TestComponentBasedRegistration:
    """Test named component registration of ignored types."""

    def test_named_str_component_sync(self, container: Container) -> None:
        """Sync: named str component is resolved."""
        api_key_type = Annotated[str, Component("api_key")]
        container.register(api_key_type, instance="secret123")

        class Service:
            def __init__(self, api_key: Annotated[str, Component("api_key")]) -> None:
                self.api_key = api_key

        result = container.resolve(Service)
        assert result.api_key == "secret123"

    @pytest.mark.asyncio
    async def test_named_str_component_async(self, container: Container) -> None:
        """Async: named str component is resolved."""
        api_key_type = Annotated[str, Component("api_key")]
        container.register(api_key_type, instance="secret123")

        class Service:
            def __init__(self, api_key: Annotated[str, Component("api_key")]) -> None:
                self.api_key = api_key

        result = await container.aresolve(Service)
        assert result.api_key == "secret123"

    def test_multiple_named_components_sync(self, container: Container) -> None:
        """Sync: multiple named components of same type are distinct."""
        host_type = Annotated[str, Component("host")]
        port_type = Annotated[int, Component("port")]
        container.register(host_type, instance="localhost")
        container.register(port_type, instance=8080)

        class Service:
            def __init__(
                self,
                host: Annotated[str, Component("host")],
                port: Annotated[int, Component("port")],
            ) -> None:
                self.host = host
                self.port = port

        result = container.resolve(Service)
        assert result.host == "localhost"
        assert result.port == 8080


class TestNestedDependencies:
    """Test ignored types as dependencies of dependencies."""

    def test_nested_dependency_uses_registered_sync(self, container: Container) -> None:
        """Sync: inner service can use registered ignored type."""
        container.register(str, instance="nested_value")

        class Inner:
            def __init__(self, value: str) -> None:
                self.value = value

        class Outer:
            def __init__(self, inner: Inner) -> None:
                self.inner = inner

        result = container.resolve(Outer)
        assert result.inner.value == "nested_value"

    @pytest.mark.asyncio
    async def test_nested_dependency_uses_registered_async(self, container: Container) -> None:
        """Async: inner service can use registered ignored type."""
        container.register(str, instance="nested_value")

        class Inner:
            def __init__(self, value: str) -> None:
                self.value = value

        class Outer:
            def __init__(self, inner: Inner) -> None:
                self.inner = inner

        result = await container.aresolve(Outer)
        assert result.inner.value == "nested_value"


class TestMultiplePrimitives:
    """Test services with multiple primitive dependencies."""

    def test_multiple_registered_primitives_sync(self, container: Container) -> None:
        """Sync: service with multiple registered primitives resolves all."""
        container.register(str, instance="string_value")
        container.register(int, instance=42)
        container.register(float, instance=3.14)
        container.register(bool, instance=True)

        class Service:
            def __init__(self, s: str, i: int, f: float, *, b: bool) -> None:
                self.s = s
                self.i = i
                self.f = f
                self.b = b

        result = container.resolve(Service)
        assert result.s == "string_value"
        assert result.i == 42
        assert result.f == 3.14
        assert result.b is True

    @pytest.mark.asyncio
    async def test_multiple_registered_primitives_async(self, container: Container) -> None:
        """Async: service with multiple registered primitives resolves all."""
        container.register(str, instance="string_value")
        container.register(int, instance=42)
        container.register(float, instance=3.14)
        container.register(bool, instance=True)

        class Service:
            def __init__(self, s: str, i: int, f: float, *, b: bool) -> None:
                self.s = s
                self.i = i
                self.f = f
                self.b = b

        result = await container.aresolve(Service)
        assert result.s == "string_value"
        assert result.i == 42
        assert result.f == 3.14
        assert result.b is True


class TestErrorCases:
    """Test error handling for unregistered ignored types."""

    def test_unregistered_without_default_raises_sync(self, container: Container) -> None:
        """Sync: unregistered ignored type without default raises error."""

        class Service:
            def __init__(self, value: str) -> None:
                self.value = value

        with pytest.raises(DIWireMissingDependenciesError):
            container.resolve(Service)

    @pytest.mark.asyncio
    async def test_unregistered_without_default_raises_async(self, container: Container) -> None:
        """Async: unregistered ignored type without default raises error."""

        class Service:
            def __init__(self, value: str) -> None:
                self.value = value

        with pytest.raises(DIWireMissingDependenciesError):
            await container.aresolve(Service)


class TestCompiledContainer:
    """Test that the fix works after container compilation."""

    def test_registered_primitive_after_compile_sync(self, container: Container) -> None:
        """Sync: compiled container resolves registered primitive."""
        container.register(str, instance="compiled_value")

        class Service:
            def __init__(self, value: str) -> None:
                self.value = value

        container.register(Service)
        container.compile()

        result = container.resolve(Service)
        assert result.value == "compiled_value"

    @pytest.mark.asyncio
    async def test_registered_primitive_after_compile_async(self, container: Container) -> None:
        """Async: compiled container resolves registered primitive."""
        container.register(str, instance="compiled_value")

        class Service:
            def __init__(self, value: str) -> None:
                self.value = value

        container.register(Service)
        container.compile()

        result = await container.aresolve(Service)
        assert result.value == "compiled_value"


class TestInjectedFunctions:
    """Test Injected with registered ignored types."""

    def test_injected_with_registered_primitive_sync(self, container: Container) -> None:
        """Sync: Injected function receives registered primitive."""
        container.register(str, instance="injected_value")

        @container.resolve()
        def get_value(value: Annotated[str, Injected()]) -> str:
            return value

        result = get_value()
        assert result == "injected_value"
