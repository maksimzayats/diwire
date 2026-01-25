import uuid
from dataclasses import dataclass, field
from inspect import signature
from typing import Annotated

import pytest

from diwire.container import Container, Injected
from diwire.exceptions import DIWireIgnoredServiceError, DIWireMissingDependenciesError
from diwire.types import FromDI, Lifetime


@pytest.fixture(scope="function")
def auto_container() -> Container:
    return Container(
        register_if_missing=True,
    )


@pytest.fixture(scope="function")
def auto_container_singleton() -> Container:
    return Container(
        register_if_missing=True,
        autoregister_default_lifetime=Lifetime.SINGLETON,
    )


def test_auto_registers_class(auto_container: Container) -> None:
    class ServiceA:
        pass

    instance = auto_container.resolve(ServiceA)
    assert isinstance(instance, ServiceA)


def test_auto_registers_class_with_dependencies(auto_container: Container) -> None:
    class ServiceA:
        pass

    class ServiceB:
        def __init__(self, service_a: ServiceA) -> None:
            self.service_a = service_a

    instance_b = auto_container.resolve(ServiceB)
    assert isinstance(instance_b, ServiceB)
    assert isinstance(instance_b.service_a, ServiceA)


def test_auto_registers_kind_singleton(auto_container_singleton: Container) -> None:
    class ServiceA:
        pass

    instance1 = auto_container_singleton.resolve(ServiceA)
    instance2 = auto_container_singleton.resolve(ServiceA)
    assert instance1 is instance2


def test_auto_registers_kind_transient(auto_container: Container) -> None:
    class ServiceA:
        pass

    instance1 = auto_container.resolve(ServiceA)
    instance2 = auto_container.resolve(ServiceA)
    assert instance1 is not instance2


def test_does_not_auto_register_ignored_class(auto_container: Container) -> None:
    class IgnoredClass:
        pass

    auto_container._autoregister_ignores.add(IgnoredClass)

    with pytest.raises(DIWireIgnoredServiceError):
        auto_container.resolve(IgnoredClass)


def test_resolve_function_returns_injected(auto_container: Container) -> None:
    class ServiceA:
        pass

    def my_func(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
        return service

    injected = auto_container.resolve(my_func)
    assert isinstance(injected, Injected)


def test_injected_resolves_transient_deps_on_each_call(auto_container: Container) -> None:
    """Transient dependencies should be created fresh on each function call."""

    class ServiceA:
        pass

    def my_func(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
        return service

    injected = auto_container.resolve(my_func)

    result1 = injected()
    result2 = injected()

    assert isinstance(result1, ServiceA)
    assert isinstance(result2, ServiceA)
    assert result1 is not result2  # Different instances on each call


def test_injected_resolves_singleton_deps_once(auto_container_singleton: Container) -> None:
    """Singleton dependencies should be the same instance on each call."""

    class ServiceA:
        pass

    def my_func(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
        return service

    injected = auto_container_singleton.resolve(my_func)

    result1 = injected()
    result2 = injected()

    assert isinstance(result1, ServiceA)
    assert result1 is result2  # Same instance on each call


def test_injected_allows_explicit_kwargs_override(auto_container: Container) -> None:
    """Explicit kwargs should override resolved dependencies."""

    class ServiceA:
        pass

    def my_func(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
        return service

    injected = auto_container.resolve(my_func)
    explicit_service = ServiceA()

    result = injected(service=explicit_service)

    assert result is explicit_service


def test_injected_preserves_function_name(auto_container: Container) -> None:
    class ServiceA:
        pass

    def my_named_function(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
        return service

    injected = auto_container.resolve(my_named_function)

    assert injected.__name__ == "my_named_function"
    assert injected.__wrapped__ is my_named_function


def test_injected_signature_excludes_injected_params(auto_container: Container) -> None:
    """Signature should only show non-injected (non-FromDI) parameters."""

    class ServiceA:
        pass

    def my_func(value: int, service: Annotated[ServiceA, FromDI()]) -> int:
        return value

    injected = auto_container.resolve(my_func)
    sig = signature(injected)

    # 'service' is marked with FromDI, should be removed from signature
    # 'value' is not marked with FromDI, should remain
    param_names = list(sig.parameters.keys())
    assert param_names == ["value"]
    assert "service" not in param_names


def test_todo(auto_container: Container) -> None:
    class ServiceA:
        pass

    @dataclass
    class ServiceB:
        service_a: Annotated[ServiceA, FromDI()]

    service_b = auto_container.resolve(ServiceB)
    assert isinstance(service_b.service_a, ServiceA)


class TestIgnoredTypesWithDefaults:
    """Tests for resolving classes with ignored types that have default values."""

    def test_resolve_class_with_ignored_type_and_default(
        self,
        auto_container: Container,
    ) -> None:
        """str with default should resolve successfully."""

        class MyClass:
            def __init__(self, name: str = "default_name") -> None:
                self.name = name

        instance = auto_container.resolve(MyClass)
        assert isinstance(instance, MyClass)
        assert instance.name == "default_name"

    def test_resolve_dataclass_with_default_factory(
        self,
        auto_container: Container,
    ) -> None:
        """Dataclass with field(default_factory=...) should work."""

        @dataclass
        class Session:
            id: str = field(default_factory=lambda: str(uuid.uuid4()))

        instance = auto_container.resolve(Session)
        assert isinstance(instance, Session)
        assert isinstance(instance.id, str)
        assert len(instance.id) > 0

    def test_resolve_class_with_ignored_type_no_default_fails(
        self,
        auto_container: Container,
    ) -> None:
        """str without default should fail with DIWireMissingDependenciesError."""

        class MyClass:
            def __init__(self, name: str) -> None:
                self.name = name

        with pytest.raises(DIWireMissingDependenciesError):
            auto_container.resolve(MyClass)

    def test_resolve_mixed_params_with_defaults(
        self,
        auto_container: Container,
    ) -> None:
        """Mix of params: some with defaults, some without."""

        class ServiceA:
            pass

        @dataclass
        class MyClass:
            service: ServiceA  # Should be resolved from container
            name: str = "default"  # Ignored type with default, should use default
            count: int = 42  # Ignored type with default, should use default

        instance = auto_container.resolve(MyClass)
        assert isinstance(instance, MyClass)
        assert isinstance(instance.service, ServiceA)
        assert instance.name == "default"
        assert instance.count == 42

    def test_resolve_dataclass_with_default_value(
        self,
        auto_container: Container,
    ) -> None:
        """Dataclass with field default (not factory) should work."""

        @dataclass
        class Config:
            timeout: int = 30
            retries: int = 3

        instance = auto_container.resolve(Config)
        assert isinstance(instance, Config)
        assert instance.timeout == 30
        assert instance.retries == 3

    def test_resolve_non_ignored_type_without_default_fails(
        self,
        auto_container: Container,
    ) -> None:
        """Non-ignored type without default and not resolvable should fail."""

        class UnregisteredService:
            pass

        class MyClass:
            def __init__(self, service: UnregisteredService) -> None:
                self.service = service

        # Add UnregisteredService to ignores to simulate unresolvable
        auto_container._autoregister_ignores.add(UnregisteredService)

        with pytest.raises(DIWireMissingDependenciesError):
            auto_container.resolve(MyClass)

    def test_resolve_non_ignored_type_with_default_uses_default_on_failure(
        self,
        auto_container: Container,
    ) -> None:
        """Non-ignored type that fails resolution but has default should use default."""

        class UnregisteredService:
            pass

        default_service = UnregisteredService()

        class MyClass:
            def __init__(self, service: UnregisteredService = default_service) -> None:
                self.service = service

        # Add to ignores to make resolution fail
        auto_container._autoregister_ignores.add(UnregisteredService)

        instance = auto_container.resolve(MyClass)
        assert isinstance(instance, MyClass)
        assert instance.service is default_service


class TestAsyncResolveFunction:
    """Tests for aresolve() on sync functions."""

    async def test_aresolve_on_sync_function_returns_injected(
        self,
        auto_container: Container,
    ) -> None:
        """aresolve() on sync function returns Injected (not AsyncInjected)."""

        class ServiceA:
            pass

        def my_func(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = await auto_container.aresolve(my_func)

        # Should be Injected, not AsyncInjected
        assert isinstance(injected, Injected)
        # Verify it's callable and works
        result = injected()
        assert isinstance(result, ServiceA)
