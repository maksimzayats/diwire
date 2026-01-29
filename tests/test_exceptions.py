"""Tests for custom exception hierarchy."""

from collections.abc import AsyncGenerator, Generator

import pytest

from diwire.container import Container
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireAsyncGeneratorFactoryDidNotYieldError,
    DIWireAsyncGeneratorFactoryWithoutScopeError,
    DIWireAutoRegistrationError,
    DIWireComponentSpecifiedError,
    DIWireError,
    DIWireGeneratorFactoryDidNotYieldError,
    DIWireGeneratorFactoryUnsupportedLifetimeError,
    DIWireGeneratorFactoryWithoutScopeError,
    DIWireIgnoredServiceError,
    DIWireMissingDependenciesError,
    DIWireNotAClassError,
    DIWireServiceNotRegisteredError,
)
from diwire.service_key import Component, ServiceKey
from diwire.types import Lifetime


class TestDIWireServiceNotRegisteredError:
    def test_raises_when_service_not_registered(self, container_no_autoregister: Container) -> None:
        class UnregisteredService:
            pass

        with pytest.raises(DIWireServiceNotRegisteredError) as exc_info:
            container_no_autoregister.resolve(UnregisteredService)

        assert exc_info.value.service_key.value is UnregisteredService
        assert "is not registered" in str(exc_info.value)


class TestDIWireMissingDependenciesError:
    def test_raises_when_dependency_cannot_be_resolved(
        self,
        container_no_autoregister: Container,
    ) -> None:
        class DependencyA:
            pass

        class ServiceB:
            def __init__(self, dep: DependencyA) -> None:
                self.dep = dep

        # Register ServiceB but not DependencyA
        container_no_autoregister.register(ServiceB)

        with pytest.raises(DIWireMissingDependenciesError) as exc_info:
            container_no_autoregister.resolve(ServiceB)

        assert exc_info.value.service_key.value is ServiceB
        assert len(exc_info.value.missing) == 1
        assert exc_info.value.missing[0].value is DependencyA
        assert "missing dependencies" in str(exc_info.value)


class TestDIWireComponentSpecifiedError:
    def test_raises_when_auto_registering_with_component(self, container: Container) -> None:
        class ServiceA:
            pass

        service_key = ServiceKey(value=ServiceA, component=Component("test_component"))

        with pytest.raises(DIWireComponentSpecifiedError) as exc_info:
            container.resolve(service_key)

        assert exc_info.value.service_key is service_key
        assert "component specified" in str(exc_info.value)


class TestDIWireIgnoredServiceError:
    def test_raises_when_auto_registering_ignored_class(self, container: Container) -> None:
        class IgnoredClass:
            pass

        container._autoregister_ignores.add(IgnoredClass)

        with pytest.raises(DIWireIgnoredServiceError) as exc_info:
            container.resolve(IgnoredClass)

        assert exc_info.value.service_key.value is IgnoredClass
        assert "ignore list" in str(exc_info.value)


class TestDIWireNotAClassError:
    def test_raises_when_auto_registering_non_class(self, container: Container) -> None:
        non_class_value = "not_a_class"

        with pytest.raises(DIWireNotAClassError) as exc_info:
            container.resolve(non_class_value)

        assert exc_info.value.service_key.value == non_class_value
        assert "not a class" in str(exc_info.value)

    def test_raises_for_integer(self, container: Container) -> None:
        with pytest.raises(DIWireNotAClassError):
            container.resolve(42)


class TestExceptionHierarchy:
    def test_service_not_registered_is_diwire_error(self) -> None:
        service_key = ServiceKey(value=str)
        exc = DIWireServiceNotRegisteredError(service_key)
        assert isinstance(exc, DIWireError)
        assert isinstance(exc, Exception)

    def test_missing_dependencies_is_diwire_error(self) -> None:
        service_key = ServiceKey(value=str)
        exc = DIWireMissingDependenciesError(service_key, [])
        assert isinstance(exc, DIWireError)
        assert isinstance(exc, Exception)

    def test_auto_registration_errors_inherit_from_base(self) -> None:
        service_key = ServiceKey(value=str)

        assert isinstance(DIWireComponentSpecifiedError(service_key), DIWireAutoRegistrationError)
        assert isinstance(DIWireIgnoredServiceError(service_key), DIWireAutoRegistrationError)
        assert isinstance(DIWireNotAClassError(service_key), DIWireAutoRegistrationError)

    def test_auto_registration_errors_are_diwire_errors(self) -> None:
        service_key = ServiceKey(value=str)

        assert isinstance(DIWireComponentSpecifiedError(service_key), DIWireError)
        assert isinstance(DIWireIgnoredServiceError(service_key), DIWireError)
        assert isinstance(DIWireNotAClassError(service_key), DIWireError)

    def test_can_catch_all_with_diwire_error(
        self,
        container_no_autoregister: Container,
        container: Container,
    ) -> None:
        class UnregisteredService:
            pass

        # Test catching DIWireServiceNotRegisteredError with DIWireError
        with pytest.raises(DIWireError):
            container_no_autoregister.resolve(UnregisteredService)

        # Test catching DIWireIgnoredServiceError with DIWireError
        container._autoregister_ignores.add(UnregisteredService)
        with pytest.raises(DIWireError):
            container.resolve(UnregisteredService)

    def test_can_catch_auto_registration_errors_with_base(self, container: Container) -> None:
        class IgnoredClass:
            pass

        container._autoregister_ignores.add(IgnoredClass)

        with pytest.raises(DIWireAutoRegistrationError):
            container.resolve(IgnoredClass)


class TestExceptionAttributes:
    def test_service_not_registered_has_service_key(self) -> None:
        class TestService:
            pass

        service_key = ServiceKey(value=TestService)
        exc = DIWireServiceNotRegisteredError(service_key)

        assert exc.service_key is service_key
        assert exc.service_key.value is TestService

    def test_missing_dependencies_has_service_key_and_missing(self) -> None:
        class ServiceA:
            pass

        class ServiceB:
            pass

        service_key = ServiceKey(value=ServiceA)
        missing = [ServiceKey(value=ServiceB)]
        exc = DIWireMissingDependenciesError(service_key, missing)

        assert exc.service_key is service_key
        assert exc.missing is missing
        assert len(exc.missing) == 1

    def test_component_specified_has_service_key(self) -> None:
        class TestService:
            pass

        service_key = ServiceKey(value=TestService, component=Component("test"))
        exc = DIWireComponentSpecifiedError(service_key)

        assert exc.service_key is service_key

    def test_ignored_service_has_service_key(self) -> None:
        class TestService:
            pass

        service_key = ServiceKey(value=TestService)
        exc = DIWireIgnoredServiceError(service_key)

        assert exc.service_key is service_key

    def test_not_a_class_has_service_key(self) -> None:
        service_key = ServiceKey(value="not_a_class")
        exc = DIWireNotAClassError(service_key)

        assert exc.service_key is service_key


class TestAsyncExceptions:
    """Tests for async-specific exceptions."""

    def test_async_dependency_in_sync_context_error_attributes(self) -> None:
        """DIWireAsyncDependencyInSyncContextError has correct attributes."""

        class ServiceA:
            pass

        class AsyncDep:
            pass

        service_key = ServiceKey(value=ServiceA)
        async_dep = ServiceKey(value=AsyncDep)
        exc = DIWireAsyncDependencyInSyncContextError(service_key, async_dep)

        assert exc.service_key is service_key
        assert exc.async_dep is async_dep
        assert "ServiceA" in str(exc)
        assert "AsyncDep" in str(exc)
        assert "aresolve" in str(exc)

    async def test_async_dependency_in_sync_context_error_raised(
        self,
        container: Container,
    ) -> None:
        """DIWireAsyncDependencyInSyncContextError is raised when resolving async dep synchronously."""

        class ServiceA:
            pass

        async def async_factory() -> ServiceA:
            return ServiceA()

        container.register(ServiceA, factory=async_factory)

        with pytest.raises(DIWireAsyncDependencyInSyncContextError) as exc_info:
            container.resolve(ServiceA)

        assert exc_info.value.service_key.value is ServiceA

    def test_async_generator_factory_without_scope_error_attributes(self) -> None:
        """DIWireAsyncGeneratorFactoryWithoutScopeError has correct attributes."""

        class ServiceA:
            pass

        service_key = ServiceKey(value=ServiceA)
        exc = DIWireAsyncGeneratorFactoryWithoutScopeError(service_key)

        assert exc.service_key is service_key
        assert "async generator" in str(exc)
        assert "scope" in str(exc)

    async def test_async_generator_factory_without_scope_error_raised(
        self,
        container: Container,
    ) -> None:
        """DIWireAsyncGeneratorFactoryWithoutScopeError is raised when using async gen without scope."""

        class ServiceA:
            pass

        async def async_gen_factory() -> AsyncGenerator[ServiceA, None]:
            yield ServiceA()

        container.register(ServiceA, factory=async_gen_factory)

        with pytest.raises(DIWireAsyncGeneratorFactoryWithoutScopeError) as exc_info:
            await container.aresolve(ServiceA)

        assert exc_info.value.service_key.value is ServiceA

    def test_async_generator_factory_did_not_yield_error_attributes(self) -> None:
        """DIWireAsyncGeneratorFactoryDidNotYieldError has correct attributes."""

        class ServiceA:
            pass

        service_key = ServiceKey(value=ServiceA)
        exc = DIWireAsyncGeneratorFactoryDidNotYieldError(service_key)

        assert exc.service_key is service_key
        assert "did not yield" in str(exc)


class TestGeneratorFactoryExceptions:
    """Tests for generator factory exceptions."""

    def test_generator_factory_did_not_yield_error_constructor(self) -> None:
        """DIWireGeneratorFactoryDidNotYieldError has correct message."""

        class ServiceA:
            pass

        service_key = ServiceKey(value=ServiceA)
        exc = DIWireGeneratorFactoryDidNotYieldError(service_key)

        assert exc.service_key is service_key
        assert "did not yield a value" in str(exc)
        assert "ServiceA" in str(exc)

    def test_generator_factory_unsupported_lifetime_error_constructor(self) -> None:
        """DIWireGeneratorFactoryUnsupportedLifetimeError has correct message."""

        class ServiceA:
            pass

        service_key = ServiceKey(value=ServiceA)
        exc = DIWireGeneratorFactoryUnsupportedLifetimeError(service_key)

        assert exc.service_key is service_key
        assert "generator" in str(exc).lower()
        assert "lifetime" in str(exc).lower()

    def test_generator_factory_did_not_yield_raised_in_sync(self) -> None:
        """DIWireGeneratorFactoryDidNotYieldError raised when generator doesn't yield."""

        class ServiceA:
            pass

        def empty_generator_factory() -> Generator[ServiceA, None, None]:
            # Generator that yields nothing
            return
            yield  # type: ignore[misc]  # unreachable but needed for generator

        container = Container()
        container.register(ServiceA, factory=empty_generator_factory, scope="request")

        with pytest.raises(DIWireGeneratorFactoryDidNotYieldError):
            with container.enter_scope("request"):
                container.resolve(ServiceA)

    def test_generator_factory_unsupported_lifetime_raised(self) -> None:
        """DIWireGeneratorFactoryUnsupportedLifetimeError raised for singleton generator."""

        class ServiceA:
            pass

        def singleton_gen_factory() -> Generator[ServiceA, None, None]:
            yield ServiceA()

        container = Container()
        # Register as SINGLETON which is not supported for generator factories
        container.register(
            ServiceA,
            factory=singleton_gen_factory,
            lifetime=Lifetime.SINGLETON,
        )

        # Generator factories require a scope - trying to resolve will fail
        # because either there's no scope (DIWireGeneratorFactoryWithoutScopeError)
        # or the lifetime is not SCOPED (DIWireGeneratorFactoryUnsupportedLifetimeError)
        with pytest.raises(  # type: ignore[call-overload]
            (
                DIWireGeneratorFactoryUnsupportedLifetimeError,
                DIWireGeneratorFactoryWithoutScopeError,
            ),
        ):
            container.resolve(ServiceA)

    async def test_async_generator_factory_did_not_yield_raised(self) -> None:
        """DIWireAsyncGeneratorFactoryDidNotYieldError raised when async gen doesn't yield."""

        class ServiceA:
            pass

        async def empty_async_gen_factory() -> AsyncGenerator[ServiceA, None]:
            return
            yield  # type: ignore[misc]  # unreachable but needed for async generator

        container = Container()
        container.register(ServiceA, factory=empty_async_gen_factory, scope="request")

        with pytest.raises(DIWireAsyncGeneratorFactoryDidNotYieldError):
            async with container.enter_scope("request"):
                await container.aresolve(ServiceA)

    async def test_async_generator_factory_unsupported_lifetime_raised(self) -> None:
        """DIWireAsyncGeneratorFactoryWithoutScopeError raised for singleton async gen."""

        class ServiceA:
            pass

        async def singleton_async_gen_factory() -> AsyncGenerator[ServiceA, None]:
            yield ServiceA()

        container = Container()
        container.register(
            ServiceA,
            factory=singleton_async_gen_factory,
            lifetime=Lifetime.SINGLETON,
        )

        # Async generator factories require a scope - trying to resolve will fail
        with pytest.raises(  # type: ignore[call-overload]
            (
                DIWireAsyncGeneratorFactoryWithoutScopeError,
                DIWireGeneratorFactoryUnsupportedLifetimeError,
            ),
        ):
            await container.aresolve(ServiceA)
