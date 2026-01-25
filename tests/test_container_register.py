"""Tests for Container.register() method."""

from typing import Annotated

import pytest

from diwire.container import Container
from diwire.exceptions import DIWireServiceNotRegisteredError
from diwire.service_key import Component, ServiceKey
from diwire.types import Lifetime


class TestRegisterClassOnly:
    def test_register_class_only(self, container: Container) -> None:
        """Register class without factory/instance."""

        class ServiceA:
            pass

        container.register(ServiceA)
        instance = container.resolve(ServiceA)

        assert isinstance(instance, ServiceA)

    def test_register_same_key_twice_overwrites(self, container: Container) -> None:
        """Later registration should overwrite previous one."""

        class ServiceA:
            value: str

            def __init__(self) -> None:
                self.value = "first"

        container.register(ServiceA)

        # Create a modified version
        class ServiceA:  # type: ignore[no-redef]
            value: str

            def __init__(self) -> None:
                self.value = "second"

        container.register(ServiceA)
        instance = container.resolve(ServiceA)

        assert instance.value == "second"


class TestRegisterWithFactory:
    def test_register_with_factory(self, container: Container) -> None:
        """Register with factory callable."""

        class ServiceA:
            def __init__(self, value: str) -> None:
                self.value = value

        class ServiceAFactory:
            def __call__(self) -> ServiceA:
                return ServiceA("factory_created")

        container.register(ServiceA, factory=ServiceAFactory)
        instance = container.resolve(ServiceA)

        assert isinstance(instance, ServiceA)
        assert instance.value == "factory_created"

    def test_factory_is_resolved_via_container(self, container: Container) -> None:
        """Factory dependencies should be resolved via container."""

        class DependencyA:
            pass

        class ServiceA:
            def __init__(self, dep: DependencyA) -> None:
                self.dep = dep

        class ServiceAFactory:
            def __init__(self, dep: DependencyA) -> None:
                self.dep = dep

            def __call__(self) -> ServiceA:
                return ServiceA(self.dep)

        container.register(ServiceA, factory=ServiceAFactory)
        instance = container.resolve(ServiceA)

        assert isinstance(instance, ServiceA)
        assert isinstance(instance.dep, DependencyA)

    def test_factory_returns_none(self, container: Container) -> None:
        """Handle factory that returns None."""

        class ServiceA:
            pass

        class ServiceAFactory:
            def __call__(self) -> ServiceA | None:
                return None

        container.register(ServiceA, factory=ServiceAFactory)
        result = container.resolve(ServiceA)

        assert result is None

    def test_factory_raises_exception(self, container: Container) -> None:
        """Exception from factory should propagate."""

        class ServiceA:
            pass

        class FactoryError(Exception):
            pass

        class ServiceAFactory:
            def __call__(self) -> ServiceA:
                msg = "Factory failed"
                raise FactoryError(msg)

        container.register(ServiceA, factory=ServiceAFactory)

        with pytest.raises(FactoryError, match="Factory failed"):
            container.resolve(ServiceA)

    def test_factory_with_dependencies(self, container: Container) -> None:
        """Factory with its own dependencies should work."""

        class DependencyA:
            pass

        class DependencyB:
            pass

        class ServiceA:
            def __init__(self, a: DependencyA, b: DependencyB) -> None:
                self.a = a
                self.b = b

        class ServiceAFactory:
            def __init__(self, a: DependencyA, b: DependencyB) -> None:
                self.a = a
                self.b = b

            def __call__(self) -> ServiceA:
                return ServiceA(self.a, self.b)

        container.register(ServiceA, factory=ServiceAFactory)
        instance = container.resolve(ServiceA)

        assert isinstance(instance.a, DependencyA)
        assert isinstance(instance.b, DependencyB)

    def test_factory_class_protocol(self, container: Container) -> None:
        """Class conforming to FactoryClassProtocol works as factory."""

        class ServiceA:
            def __init__(self, value: int) -> None:
                self.value = value

        class ServiceAFactory:
            def __call__(self) -> ServiceA:
                return ServiceA(42)

        container.register(ServiceA, factory=ServiceAFactory)
        instance = container.resolve(ServiceA)

        assert instance.value == 42


class TestRegisterWithInstance:
    def test_register_with_instance(self, container: Container) -> None:
        """Register with pre-created instance."""

        class ServiceA:
            def __init__(self, value: str) -> None:
                self.value = value

        pre_created = ServiceA("pre_created")
        container.register(ServiceA, instance=pre_created)
        instance = container.resolve(ServiceA)

        assert instance is pre_created

    def test_register_none_as_instance(self, container: Container) -> None:
        """Instance explicitly set to None."""

        class ServiceA:
            pass

        container.register(ServiceA, instance=None)
        instance = container.resolve(ServiceA)

        assert isinstance(instance, ServiceA)

    def test_register_both_factory_and_instance(self, container: Container) -> None:
        """When both factory and instance are provided, instance wins."""

        class ServiceA:
            def __init__(self, value: str = "default") -> None:
                self.value = value

        class ServiceAFactory:
            def __call__(self) -> ServiceA:
                return ServiceA("from_factory")

        pre_created = ServiceA("from_instance")
        container.register(ServiceA, factory=ServiceAFactory, instance=pre_created)
        instance = container.resolve(ServiceA)

        # Instance takes precedence over factory
        assert instance is pre_created

    def test_instance_always_returns_same(self, container: Container) -> None:
        """Instance registration should always return the same object."""

        class ServiceA:
            pass

        pre_created = ServiceA()
        container.register(ServiceA, instance=pre_created)

        instance1 = container.resolve(ServiceA)
        instance2 = container.resolve(ServiceA)

        assert instance1 is instance2
        assert instance1 is pre_created

    def test_instance_cached_in_singletons(self, container: Container) -> None:
        """Instance should be stored in _singletons."""

        class ServiceA:
            pass

        pre_created = ServiceA()
        container.register(ServiceA, instance=pre_created)
        container.resolve(ServiceA)

        service_key = ServiceKey.from_value(ServiceA)
        assert service_key in container._singletons
        assert container._singletons[service_key] is pre_created

    def test_reregister_instance_overwrites_cached_singleton(self, container: Container) -> None:
        """Re-registering with a new instance should overwrite cached singleton."""
        container.register(int, instance=1)
        assert container.resolve(int) == 1

        container.register(int, instance=2)
        assert container.resolve(int) == 2

    def test_reregister_instance_updates_singletons_cache(self, container: Container) -> None:
        """Re-registering should update _singletons immediately, not just registry."""
        container.register(int, instance=1)
        container.resolve(int)  # Cache in _singletons

        service_key = ServiceKey.from_value(int)
        assert container._singletons[service_key] == 1

        container.register(int, instance=2)
        # Should update _singletons without needing to resolve
        assert container._singletons[service_key] == 2

    def test_reregister_instance_in_nested_scope(self, container: Container) -> None:
        """Re-registering instance in nested scope should work correctly."""
        with container.start_scope("outer") as outer:
            c1 = outer.resolve(Container)
            c1.register(int, instance=1)
            assert c1.resolve(int) == 1

            with outer.start_scope("inner") as inner:
                c2 = inner.resolve(Container)
                c2.register(int, instance=2)
                assert c2.resolve(int) == 2

            # After inner scope exits, outer scope should still see latest value
            assert c1.resolve(int) == 2

    def test_reregister_instance_multiple_times(self, container: Container) -> None:
        """Multiple re-registrations should always use the latest value."""
        for i in range(5):
            container.register(int, instance=i)
            assert container.resolve(int) == i


class TestRegisterWithLifetime:
    def test_register_with_lifetime_singleton(self, container: Container) -> None:
        """Verify lifetime singleton works."""

        class ServiceA:
            pass

        container.register(ServiceA, lifetime=Lifetime.SINGLETON)

        instance1 = container.resolve(ServiceA)
        instance2 = container.resolve(ServiceA)

        assert instance1 is instance2

    def test_register_with_lifetime_transient(self, container: Container) -> None:
        """Verify lifetime transient works."""

        class ServiceA:
            pass

        container.register(ServiceA, lifetime=Lifetime.TRANSIENT)

        instance1 = container.resolve(ServiceA)
        instance2 = container.resolve(ServiceA)

        assert instance1 is not instance2


class TestRegisterWithServiceKey:
    def test_register_with_service_key_directly(self, container: Container) -> None:
        """Use ServiceKey as key."""

        class ServiceA:
            pass

        service_key = ServiceKey(value=ServiceA)
        container.register(service_key)
        instance = container.resolve(service_key)

        assert isinstance(instance, ServiceA)

    def test_register_with_annotated_type(self, container: Container) -> None:
        """Annotated[T, ...] as key."""

        class ServiceA:
            pass

        annotated_type = Annotated[ServiceA, "some_metadata"]
        container.register(annotated_type)
        instance = container.resolve(annotated_type)

        assert isinstance(instance, ServiceA)

    def test_register_with_component(self, container: Container) -> None:
        """ServiceKey with Component."""

        class ServiceA:
            def __init__(self, value: str = "default") -> None:
                self.value = value

        # Register two different implementations with components
        service_key_a = ServiceKey(value=ServiceA, component=Component("version_a"))
        service_key_b = ServiceKey(value=ServiceA, component=Component("version_b"))

        instance_a = ServiceA("version_a_value")
        instance_b = ServiceA("version_b_value")

        container.register(service_key_a, instance=instance_a)
        container.register(service_key_b, instance=instance_b)

        resolved_a = container.resolve(service_key_a)
        resolved_b = container.resolve(service_key_b)

        assert resolved_a is instance_a
        assert resolved_b is instance_b
        assert resolved_a.value == "version_a_value"
        assert resolved_b.value == "version_b_value"


class TestResolveManualRegistration:
    def test_resolve_manual_registration_without_auto(
        self,
        container_no_autoregister: Container,
    ) -> None:
        """Manual registration works with register_if_missing=False."""

        class ServiceA:
            pass

        container_no_autoregister.register(ServiceA)
        instance = container_no_autoregister.resolve(ServiceA)

        assert isinstance(instance, ServiceA)

    def test_resolve_unregistered_raises_without_auto(
        self,
        container_no_autoregister: Container,
    ) -> None:
        """Resolving unregistered service without auto-registration raises."""

        class ServiceA:
            pass

        with pytest.raises(DIWireServiceNotRegisteredError):
            container_no_autoregister.resolve(ServiceA)


class TestRegisterAsyncFactory:
    """Tests for async factory registration."""

    async def test_is_async_auto_detected_from_async_factory(
        self,
        container: Container,
    ) -> None:
        """is_async is auto-detected from async factory function."""

        class ServiceA:
            pass

        async def async_factory() -> ServiceA:
            return ServiceA()

        container.register(ServiceA, factory=async_factory)

        # Should work with aresolve
        instance = await container.aresolve(ServiceA)
        assert isinstance(instance, ServiceA)

    async def test_explicit_is_async_override(self, container: Container) -> None:
        """Explicit is_async=True overrides auto-detection."""

        class ServiceA:
            pass

        def sync_factory() -> ServiceA:
            return ServiceA()

        container.register(ServiceA, factory=sync_factory, is_async=True)

        # Should be treated as async
        from diwire.exceptions import DIWireAsyncDependencyInSyncContextError

        with pytest.raises(DIWireAsyncDependencyInSyncContextError):
            container.resolve(ServiceA)

    async def test_async_generator_factory_detection(self, container: Container) -> None:
        """Async generator factory is detected correctly."""
        from collections.abc import AsyncGenerator

        class ServiceA:
            pass

        cleanup_called = []

        async def async_gen_factory() -> AsyncGenerator[ServiceA, None]:
            try:
                yield ServiceA()
            finally:
                cleanup_called.append(True)

        container.register(
            ServiceA,
            factory=async_gen_factory,
            scope="test",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        async with container.start_scope("test"):
            instance = await container.aresolve(ServiceA)
            assert isinstance(instance, ServiceA)
            assert cleanup_called == []

        assert cleanup_called == [True]
