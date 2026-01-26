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


class TestRegisterWithCallableFactory:
    """Tests for registering services with callable factories (functions/methods/lambdas)."""

    def test_register_with_function_factory(self, container: Container) -> None:
        """Register with a function factory."""

        class ServiceA:
            def __init__(self, value: str) -> None:
                self.value = value

        def create_service_a() -> ServiceA:
            return ServiceA("from_function")

        container.register(ServiceA, factory=create_service_a)
        instance = container.resolve(ServiceA)

        assert isinstance(instance, ServiceA)
        assert instance.value == "from_function"

    def test_register_with_method_factory(self, container: Container) -> None:
        """Register with a method factory (like ContextVar.get)."""
        from contextvars import ContextVar

        class Request:
            def __init__(self, request_id: str) -> None:
                self.request_id = request_id

        request_var: ContextVar[Request] = ContextVar("request")
        expected_request = Request("test-123")
        request_var.set(expected_request)

        container.register(Request, factory=request_var.get)
        instance = container.resolve(Request)

        assert instance is expected_request

    def test_register_with_lambda_factory(self, container: Container) -> None:
        """Register with a lambda factory."""

        class ServiceA:
            def __init__(self, value: int) -> None:
                self.value = value

        container.register(ServiceA, factory=lambda: ServiceA(99))
        instance = container.resolve(ServiceA)

        assert isinstance(instance, ServiceA)
        assert instance.value == 99

    def test_class_factory_still_works(self, container: Container) -> None:
        """Ensure class factories (original behavior) still work."""

        class ServiceA:
            def __init__(self, value: str) -> None:
                self.value = value

        class ServiceAFactory:
            def __call__(self) -> ServiceA:
                return ServiceA("from_class_factory")

        container.register(ServiceA, factory=ServiceAFactory)
        instance = container.resolve(ServiceA)

        assert isinstance(instance, ServiceA)
        assert instance.value == "from_class_factory"

    async def test_async_resolve_with_function_factory(self, container: Container) -> None:
        """Async resolution with a function factory."""

        class ServiceA:
            def __init__(self, value: str) -> None:
                self.value = value

        def create_service_a() -> ServiceA:
            return ServiceA("async_function")

        container.register(ServiceA, factory=create_service_a)
        instance = await container.aresolve(ServiceA)

        assert isinstance(instance, ServiceA)
        assert instance.value == "async_function"

    async def test_async_resolve_with_method_factory(self, container: Container) -> None:
        """Async resolution with a method factory."""
        from contextvars import ContextVar

        class Request:
            def __init__(self, request_id: str) -> None:
                self.request_id = request_id

        request_var: ContextVar[Request] = ContextVar("request")
        expected_request = Request("async-test-456")
        request_var.set(expected_request)

        container.register(Request, factory=request_var.get)
        instance = await container.aresolve(Request)

        assert instance is expected_request

    def test_callable_factory_with_singleton_lifetime(self, container: Container) -> None:
        """Callable factory with singleton lifetime returns same instance."""
        call_count = 0

        class ServiceA:
            def __init__(self, value: int) -> None:
                self.value = value

        def create_service_a() -> ServiceA:
            nonlocal call_count
            call_count += 1
            return ServiceA(call_count)

        container.register(ServiceA, factory=create_service_a, lifetime=Lifetime.SINGLETON)
        instance1 = container.resolve(ServiceA)
        instance2 = container.resolve(ServiceA)

        assert instance1 is instance2
        assert call_count == 1

    def test_compiled_callable_factory(self, container: Container) -> None:
        """Callable factory works with compiled container."""
        call_count = 0

        class ServiceA:
            def __init__(self, value: int) -> None:
                self.value = value

        def create_service_a() -> ServiceA:
            nonlocal call_count
            call_count += 1
            return ServiceA(call_count)

        container.register(ServiceA, factory=create_service_a)
        container.compile()
        instance = container.resolve(ServiceA)

        assert isinstance(instance, ServiceA)
        assert instance.value == 1


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


class TestFactoryFunctionAutoInjectsDependencies:
    """Tests for factory functions auto-injecting all dependencies without FromDI."""

    def test_factory_function_auto_injects_dependencies(self, container: Container) -> None:
        """Function factory should have all typed params auto-injected."""

        class Request:
            def __init__(self, request_id: str = "default") -> None:
                self.request_id = request_id

        class Service:
            pass

        def service_factory(request: Request) -> Service:
            assert isinstance(request, Request)
            return Service()

        container.register(Request, instance=Request("test-123"))
        container.register(Service, factory=service_factory)
        instance = container.resolve(Service)

        assert isinstance(instance, Service)

    async def test_factory_async_generator_auto_injects_dependencies(
        self,
        container: Container,
    ) -> None:
        """Async generator factory should have all typed params auto-injected."""
        from collections.abc import AsyncGenerator

        class Request:
            def __init__(self, request_id: str = "default") -> None:
                self.request_id = request_id

        class Service:
            pass

        cleanup_called = []
        received_request = []

        async def service_factory(request: Request) -> AsyncGenerator[Service, None]:
            received_request.append(request)
            try:
                yield Service()
            finally:
                cleanup_called.append(True)

        expected_request = Request("test-456")
        container.register(Request, instance=expected_request)
        container.register(
            Service,
            factory=service_factory,
            scope="request",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        async with container.start_scope("request"):
            instance = await container.aresolve(Service)
            assert isinstance(instance, Service)
            assert received_request[0] is expected_request
            assert cleanup_called == []

        assert cleanup_called == [True]

    def test_factory_with_mixed_deps_and_defaults(self, container: Container) -> None:
        """Factory with some dependencies and some defaults should work."""

        class DependencyA:
            pass

        class Service:
            pass

        def service_factory(
            dep: DependencyA,
            config: str = "default_config",
        ) -> Service:
            assert isinstance(dep, DependencyA)
            assert config == "default_config"
            return Service()

        container.register(Service, factory=service_factory)
        instance = container.resolve(Service)

        assert isinstance(instance, Service)

    def test_factory_class_still_works(self, container: Container) -> None:
        """Class factories should still work with the new changes."""

        class DependencyA:
            pass

        class Service:
            def __init__(self, value: str) -> None:
                self.value = value

        class ServiceFactory:
            def __init__(self, dep: DependencyA) -> None:
                self.dep = dep

            def __call__(self) -> Service:
                return Service("from_class_factory")

        container.register(Service, factory=ServiceFactory)
        instance = container.resolve(Service)

        assert isinstance(instance, Service)
        assert instance.value == "from_class_factory"

    async def test_async_factory_function_auto_injects_dependencies(
        self,
        container: Container,
    ) -> None:
        """Async factory function should have all typed params auto-injected."""

        class Request:
            def __init__(self, request_id: str = "default") -> None:
                self.request_id = request_id

        class Service:
            pass

        received_request = []

        async def service_factory(request: Request) -> Service:
            received_request.append(request)
            return Service()

        expected_request = Request("async-test-789")
        container.register(Request, instance=expected_request)
        container.register(Service, factory=service_factory)
        instance = await container.aresolve(Service)

        assert isinstance(instance, Service)
        assert received_request[0] is expected_request

    def test_factory_sync_generator_auto_injects_dependencies(self, container: Container) -> None:
        """Sync generator factory should have all typed params auto-injected."""
        from collections.abc import Generator

        class Request:
            def __init__(self, request_id: str = "default") -> None:
                self.request_id = request_id

        class Service:
            pass

        cleanup_called = []
        received_request = []

        def service_factory(request: Request) -> Generator[Service, None, None]:
            received_request.append(request)
            try:
                yield Service()
            finally:
                cleanup_called.append(True)

        expected_request = Request("gen-test-101")
        container.register(Request, instance=expected_request)
        container.register(
            Service,
            factory=service_factory,
            scope="request",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with container.start_scope("request"):
            instance = container.resolve(Service)
            assert isinstance(instance, Service)
            assert received_request[0] is expected_request
            assert cleanup_called == []

        assert cleanup_called == [True]

    def test_factory_function_with_multiple_dependencies(self, container: Container) -> None:
        """Factory function with multiple dependencies should resolve all."""

        class DependencyA:
            pass

        class DependencyB:
            pass

        class Service:
            pass

        received_deps: list[tuple[DependencyA, DependencyB]] = []

        def service_factory(a: DependencyA, b: DependencyB) -> Service:
            received_deps.append((a, b))
            return Service()

        container.register(Service, factory=service_factory)
        instance = container.resolve(Service)

        assert isinstance(instance, Service)
        assert len(received_deps) == 1
        assert isinstance(received_deps[0][0], DependencyA)
        assert isinstance(received_deps[0][1], DependencyB)


class TestBuiltinCallableFactoryWithoutCompilation:
    """Tests for built-in callable factories (like ContextVar.get) without compilation."""

    def test_builtin_callable_factory_without_compilation_sync(
        self,
        container: Container,
    ) -> None:
        """ContextVar.get as factory works in non-compiled container.

        This test covers line 1419 in container.py where a built-in callable
        factory is invoked directly in the non-compiled sync path.
        """
        from contextvars import ContextVar

        class Request:
            def __init__(self, request_id: str) -> None:
                self.request_id = request_id

        request_var: ContextVar[Request] = ContextVar("request")
        expected_request = Request("test-no-compile")
        request_var.set(expected_request)

        # Create container without auto-compile
        c = Container(register_if_missing=True, auto_compile=False)
        c.register(Request, factory=request_var.get)

        instance = c.resolve(Request)
        assert instance is expected_request

    async def test_builtin_callable_factory_without_compilation_async(
        self,
        container: Container,
    ) -> None:
        """ContextVar.get as factory works in async non-compiled resolution.

        This test covers the async path (line 1688) where a built-in callable
        factory is invoked directly in the non-compiled async path.
        """
        from contextvars import ContextVar

        class Request:
            def __init__(self, request_id: str) -> None:
                self.request_id = request_id

        request_var: ContextVar[Request] = ContextVar("request")
        expected_request = Request("async-no-compile")
        request_var.set(expected_request)

        # Create container without auto-compile
        c = Container(register_if_missing=True, auto_compile=False)
        c.register(Request, factory=request_var.get)

        instance = await c.aresolve(Request)
        assert instance is expected_request


class TestFunctionFactoryMissingDependencies:
    """Tests for function factory with missing (unresolvable) dependencies."""

    def test_function_factory_with_missing_dependencies_raises_error_sync(
        self,
        container_no_autoregister: Container,
    ) -> None:
        """Function factory with unresolvable deps raises DIWireMissingDependenciesError.

        This test covers line 1415 in container.py where a function factory
        has dependencies that cannot be resolved.
        """
        from diwire.exceptions import DIWireMissingDependenciesError

        # Create a type that cannot be auto-registered (abstract or uninstantiable)
        class UnregisteredDep:
            """Dependency that is not registered."""

        class Service:
            pass

        def service_factory(dep: UnregisteredDep) -> Service:
            return Service()

        # Use container without auto-registration so UnregisteredDep won't be found
        container_no_autoregister.register(Service, factory=service_factory)

        with pytest.raises(DIWireMissingDependenciesError):
            container_no_autoregister.resolve(Service)

    async def test_function_factory_with_missing_dependencies_raises_error_async(
        self,
        container_no_autoregister: Container,
    ) -> None:
        """Async: Function factory with unresolvable deps raises error.

        This test covers line 1685 in container.py where a function factory
        has dependencies that cannot be resolved in the async path.
        """
        from diwire.exceptions import DIWireMissingDependenciesError

        class UnregisteredDep:
            """Dependency that is not registered."""

        class Service:
            pass

        def service_factory(dep: UnregisteredDep) -> Service:
            return Service()

        # Use container without auto-registration
        container_no_autoregister.register(Service, factory=service_factory)

        with pytest.raises(DIWireMissingDependenciesError):
            await container_no_autoregister.aresolve(Service)
