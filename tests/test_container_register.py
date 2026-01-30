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
        with container.enter_scope("outer") as outer:
            c1 = outer.resolve(Container)
            c1.register(int, instance=1)
            assert c1.resolve(int) == 1

            with outer.enter_scope("inner") as inner:
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
        """Manual registration works with autoregister=False."""

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
            lifetime=Lifetime.SCOPED,
        )

        async with container.enter_scope("test"):
            instance = await container.aresolve(ServiceA)
            assert isinstance(instance, ServiceA)
            assert cleanup_called == []

        assert cleanup_called == [True]


class TestFactoryFunctionAutoInjectsDependencies:
    """Tests for factory functions auto-injecting all dependencies without Injected."""

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
            lifetime=Lifetime.SCOPED,
        )

        async with container.enter_scope("request"):
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
            lifetime=Lifetime.SCOPED,
        )

        with container.enter_scope("request"):
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
        c = Container(autoregister=True, auto_compile=False)
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
        c = Container(autoregister=True, auto_compile=False)
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


class TestRegisterClassAsDecorator:
    """Tests for using @container.register as a class decorator."""

    def test_bare_decorator_registers_class(self, container: Container) -> None:
        """@container.register on a class should register it."""

        @container.register
        class MyService:
            pass

        instance = container.resolve(MyService)
        assert isinstance(instance, MyService)

    def test_bare_decorator_returns_original_class(self, container: Container) -> None:
        """@container.register should return the original class unchanged."""

        @container.register
        class MyService:
            pass

        # The class should be the same object
        assert MyService.__name__ == "MyService"
        assert hasattr(MyService, "__init__")

    def test_decorator_with_lifetime_singleton(self, container: Container) -> None:
        """@container.register(lifetime=Lifetime.SINGLETON) should create singletons."""

        @container.register(lifetime=Lifetime.SINGLETON)
        class MySingleton:
            pass

        instance1 = container.resolve(MySingleton)
        instance2 = container.resolve(MySingleton)
        assert instance1 is instance2

    def test_decorator_with_lifetime_transient(self, container: Container) -> None:
        """@container.register(lifetime=Lifetime.TRANSIENT) should create new instances."""

        @container.register(lifetime=Lifetime.TRANSIENT)
        class MyTransient:
            pass

        instance1 = container.resolve(MyTransient)
        instance2 = container.resolve(MyTransient)
        assert instance1 is not instance2

    def test_decorator_with_interface_key(self, container: Container) -> None:
        """@container.register(Interface) should register class under interface."""

        class IService:
            def do_something(self) -> str:
                raise NotImplementedError

        @container.register(IService)
        class ServiceImpl(IService):  # type: ignore[call-arg]
            def do_something(self) -> str:
                return "implemented"

        instance = container.resolve(IService)
        assert isinstance(instance, ServiceImpl)
        assert instance.do_something() == "implemented"

    def test_decorator_with_scope(self, container: Container) -> None:
        """@container.register(lifetime=SCOPED, scope=...) should work."""

        @container.register(lifetime=Lifetime.SCOPED, scope="request")
        class RequestService:
            pass

        with container.enter_scope("request"):
            instance1 = container.resolve(RequestService)
            instance2 = container.resolve(RequestService)
            assert instance1 is instance2

    def test_decorator_scoped_without_scope_raises(self, container: Container) -> None:
        """SCOPED without scope should raise error."""
        from diwire.exceptions import DIWireScopedWithoutScopeError

        with pytest.raises(DIWireScopedWithoutScopeError):

            @container.register(lifetime=Lifetime.SCOPED)
            class InvalidService:
                pass

    def test_decorator_with_multiple_params(self, container: Container) -> None:
        """Decorator with multiple parameters should work."""

        class ILogger:
            pass

        @container.register(ILogger, lifetime=Lifetime.SINGLETON)
        class Logger(ILogger):
            pass

        instance1 = container.resolve(ILogger)
        instance2 = container.resolve(ILogger)
        assert instance1 is instance2
        assert isinstance(instance1, Logger)

    def test_decorator_same_type_as_interface_key(self, container: Container) -> None:
        """Decorating a class with its own type as interface_key should work."""
        # This tests the edge case where interface_key is target (same class)
        # The registration happens in Case 4, decorator just returns the class
        # Note: We need to forward-declare the class name to use it in the decorator

        # Define name first, then decorate
        class MyService:
            pass

        # Use global to get the class defined above and decorate
        decorated = container.register(MyService, lifetime=Lifetime.SINGLETON)(MyService)
        assert decorated is MyService

        instance1 = container.resolve(MyService)
        instance2 = container.resolve(MyService)
        assert instance1 is instance2
        assert isinstance(instance1, MyService)


class TestRegisterFactoryAsDecorator:
    """Tests for using @container.register as a factory function decorator."""

    def test_bare_factory_decorator_infers_type_from_return_annotation(
        self,
        container: Container,
    ) -> None:
        """@container.register on a function should infer type from return annotation."""

        class Database:
            def __init__(self, host: str, port: int) -> None:
                self.host = host
                self.port = port

        @container.register
        def create_database() -> Database:
            return Database(host="localhost", port=5432)

        instance = container.resolve(Database)
        assert isinstance(instance, Database)
        assert instance.host == "localhost"
        assert instance.port == 5432

    def test_factory_decorator_with_explicit_key(self, container: Container) -> None:
        """@container.register(Type) should use explicit type as registration key."""

        class IDatabase:
            pass

        class PostgresDB(IDatabase):
            pass

        @container.register(IDatabase)  # type: ignore[misc, call-arg]
        def create_database() -> PostgresDB:
            return PostgresDB()

        instance = container.resolve(IDatabase)
        assert isinstance(instance, PostgresDB)

    def test_factory_decorator_key_overrides_return_annotation(
        self,
        container: Container,
    ) -> None:
        """Explicit key should take precedence over return annotation."""

        class IService:
            pass

        class ServiceImpl(IService):
            pass

        @container.register(IService)  # type: ignore[misc, call-arg]
        def create_service() -> ServiceImpl:
            return ServiceImpl()

        # Should be registered under IService, not ServiceImpl
        instance = container.resolve(IService)
        assert isinstance(instance, ServiceImpl)

    def test_factory_decorator_returns_original_function(self, container: Container) -> None:
        """@container.register should return the original function unchanged."""

        class Config:
            pass

        @container.register
        def create_config() -> Config:
            return Config()

        # The function should still be callable directly
        direct_result = create_config()
        assert isinstance(direct_result, Config)

    def test_factory_decorator_with_lifetime_singleton(self, container: Container) -> None:
        """@container.register(lifetime=SINGLETON) should create singleton."""
        call_count = 0

        class Config:
            pass

        @container.register(lifetime=Lifetime.SINGLETON)
        def create_config() -> Config:
            nonlocal call_count
            call_count += 1
            return Config()

        instance1 = container.resolve(Config)
        instance2 = container.resolve(Config)
        assert instance1 is instance2
        assert call_count == 1

    def test_factory_decorator_with_dependencies_auto_injected(
        self,
        container: Container,
    ) -> None:
        """Factory function dependencies should be auto-injected."""

        class Database:
            pass

        class Logger:
            pass

        class UserRepository:
            def __init__(self, db: Database, logger: Logger) -> None:
                self.db = db
                self.logger = logger

        @container.register
        def create_user_repo(db: Database, logger: Logger) -> UserRepository:
            return UserRepository(db, logger)

        instance = container.resolve(UserRepository)
        assert isinstance(instance, UserRepository)
        assert isinstance(instance.db, Database)
        assert isinstance(instance.logger, Logger)

    async def test_async_factory_decorator(self, container: Container) -> None:
        """Async factory function should work with decorator."""

        class AsyncService:
            def __init__(self, *, initialized: bool = False) -> None:
                self.initialized = initialized

        @container.register(lifetime=Lifetime.SINGLETON)
        async def create_async_service() -> AsyncService:
            service = AsyncService()
            # Simulate async initialization
            service.initialized = True
            return service

        instance = await container.aresolve(AsyncService)
        assert isinstance(instance, AsyncService)
        assert instance.initialized is True

    async def test_async_factory_decorator_auto_detected(self, container: Container) -> None:
        """Async factory should be auto-detected without is_async parameter."""

        class AsyncService:
            pass

        @container.register
        async def create_async_service() -> AsyncService:
            return AsyncService()

        # Should require aresolve
        from diwire.exceptions import DIWireAsyncDependencyInSyncContextError

        with pytest.raises(DIWireAsyncDependencyInSyncContextError):
            container.resolve(AsyncService)

        instance = await container.aresolve(AsyncService)
        assert isinstance(instance, AsyncService)

    def test_factory_decorator_without_return_annotation_raises(
        self,
        container: Container,
    ) -> None:
        """Factory without return annotation and no provides should raise."""
        from diwire.exceptions import DIWireDecoratorFactoryMissingReturnAnnotationError

        with pytest.raises(DIWireDecoratorFactoryMissingReturnAnnotationError):

            @container.register
            def create_something():  # type: ignore[no-untyped-def]
                return object()

    def test_factory_decorator_with_none_return_annotation_raises(
        self,
        container: Container,
    ) -> None:
        """Factory with None return annotation and no provides should raise."""
        from diwire.exceptions import DIWireDecoratorFactoryMissingReturnAnnotationError

        with pytest.raises(DIWireDecoratorFactoryMissingReturnAnnotationError):

            @container.register
            def create_nothing() -> None:
                pass

    def test_parameterized_factory_decorator_without_return_annotation_raises(
        self,
        container: Container,
    ) -> None:
        """Parameterized factory decorator without return annotation should raise."""
        from diwire.exceptions import DIWireDecoratorFactoryMissingReturnAnnotationError

        with pytest.raises(DIWireDecoratorFactoryMissingReturnAnnotationError):

            @container.register(lifetime=Lifetime.SINGLETON)
            def create_something():  # type: ignore[no-untyped-def]
                return object()


class TestDecoratorBackwardCompatibility:
    """Ensure existing direct-call API continues to work."""

    def test_direct_call_with_params_still_works(self, container: Container) -> None:
        """container.register(MyClass, factory=...) direct call should work."""

        class ServiceA:
            pass

        def factory() -> ServiceA:
            return ServiceA()

        # Direct call with factory returns None
        result = container.register(ServiceA, factory=factory)
        assert result is None

        instance = container.resolve(ServiceA)
        assert isinstance(instance, ServiceA)

    def test_bare_class_registration_returns_compatible_class(self, container: Container) -> None:
        """container.register(MyClass) returns a class compatible with MyClass."""

        class ServiceA:
            pass

        # Bare class registration returns a proxy class that inherits from the original
        # This allows @container.register(Type) on functions/classes to work
        result = container.register(ServiceA)
        # Result is a subclass of ServiceA (proxy pattern for decorator compatibility)
        assert issubclass(result, ServiceA)

        instance = container.resolve(ServiceA)
        assert isinstance(instance, ServiceA)
        assert isinstance(instance, result)

    def test_direct_call_with_factory_returns_none(self, container: Container) -> None:
        """container.register(Type, factory=...) should return None."""

        class ServiceA:
            pass

        def create_service() -> ServiceA:
            return ServiceA()

        result = container.register(ServiceA, factory=create_service)
        assert result is None

    def test_direct_call_with_instance_returns_none(self, container: Container) -> None:
        """container.register(Type, instance=...) should return None."""

        class ServiceA:
            pass

        result = container.register(ServiceA, instance=ServiceA())
        assert result is None


class TestProxyClassFeatures:
    """Test proxy class features returned by container.register(Type)."""

    def test_proxy_class_getitem_forwards_to_original(self, container: Container) -> None:
        """Proxy class __class_getitem__ should forward to original for generics."""
        from typing import Generic, TypeVar

        T = TypeVar("T")

        class GenericBox(Generic[T]):
            def __init__(self, value: T) -> None:
                self.value = value

        # Register returns a proxy class
        proxy = container.register(GenericBox)

        # __class_getitem__ should forward to original
        specialized = proxy[int]

        # The specialized type should be usable for isinstance checks
        assert hasattr(specialized, "__origin__") or specialized is not None

    def test_proxy_factory_registration_via_new(self, container: Container) -> None:
        """Proxy class __new__ should handle factory function registration."""

        class Config:
            def __init__(self, value: str) -> None:
                self.value = value

        # Get proxy class
        config_proxy = container.register(Config)

        # Use proxy as decorator on a factory function
        @config_proxy  # type: ignore[misc, arg-type]
        def create_config() -> Config:
            return Config("from-factory")

        # Factory should be registered
        config = container.resolve(Config)
        assert config.value == "from-factory"
        # Function should be returned unchanged
        assert callable(create_config)

    def test_proxy_normal_instantiation(self, container: Container) -> None:
        """Proxy class __new__ should create instances normally."""

        class SimpleClass:
            def __init__(self, value: int) -> None:
                self.value = value

        # Get proxy class
        simple_proxy = container.register(SimpleClass)

        # Direct instantiation should work
        instance = simple_proxy(42)
        assert instance.value == 42
        assert isinstance(instance, simple_proxy)
        assert isinstance(instance, SimpleClass)

    def test_proxy_instantiation_with_non_callable_arg(self, container: Container) -> None:
        """Proxy class __new__ falls through to normal instantiation for non-type non-callable."""

        class SimpleClass:
            def __init__(self, value: int = 0) -> None:
                self.value = value

        # Get proxy class
        simple_proxy = container.register(SimpleClass)

        # Passing a non-callable, non-type arg should create an instance
        instance = simple_proxy()
        assert instance.value == 0

    def test_proxy_preserves_metadata_without_doc(self, container: Container) -> None:
        """Proxy class preserves metadata even when original has no __doc__."""

        class NoDocClass:
            pass

        # Remove __doc__ if present
        NoDocClass.__doc__ = None  # type: ignore[assignment]

        # Get proxy class
        no_doc_proxy = container.register(NoDocClass)

        # Should preserve name and module
        assert no_doc_proxy.__name__ == "NoDocClass"
        assert no_doc_proxy.__module__ == NoDocClass.__module__


class TestDecoratorWithDataclasses:
    """Test decorator integration with dataclasses."""

    def test_decorator_with_dataclass(self, container: Container) -> None:
        """@container.register should work with @dataclass."""
        from dataclasses import dataclass

        @container.register
        @dataclass
        class Config:
            debug: bool = True
            port: int = 8080

        instance = container.resolve(Config)
        assert isinstance(instance, Config)
        assert instance.debug is True
        assert instance.port == 8080

    def test_decorator_order_with_dataclass(self, container: Container) -> None:
        """Decorator order should not matter for dataclasses."""
        from dataclasses import dataclass

        @dataclass
        @container.register
        class Config:
            name: str = "default"

        instance = container.resolve(Config)
        assert isinstance(instance, Config)
        assert instance.name == "default"


class TestDecoratorWithDependencies:
    """Test decorated classes with dependencies."""

    def test_decorated_class_with_dependencies(self, container: Container) -> None:
        """Decorated class with constructor dependencies should work."""

        @container.register
        class Database:
            pass

        @container.register
        class Repository:
            def __init__(self, db: Database) -> None:
                self.db = db

        instance = container.resolve(Repository)
        assert isinstance(instance, Repository)
        assert isinstance(instance.db, Database)

    def test_multiple_decorated_classes_with_dependencies(self, container: Container) -> None:
        """Multiple decorated classes forming a dependency chain should work."""

        @container.register
        class Config:
            pass

        @container.register
        class Database:
            def __init__(self, config: Config) -> None:
                self.config = config

        @container.register
        class Repository:
            def __init__(self, db: Database) -> None:
                self.db = db

        @container.register
        class Service:
            def __init__(self, repo: Repository) -> None:
                self.repo = repo

        instance = container.resolve(Service)
        assert isinstance(instance, Service)
        assert isinstance(instance.repo, Repository)
        assert isinstance(instance.repo.db, Database)
        assert isinstance(instance.repo.db.config, Config)

    def test_factory_with_decorated_class_dependencies(self, container: Container) -> None:
        """Factory function using decorated class dependencies should work."""

        @container.register
        class Logger:
            pass

        @container.register
        class Config:
            pass

        class App:
            def __init__(self, logger: Logger, config: Config) -> None:
                self.logger = logger
                self.config = config

        @container.register
        def create_app(logger: Logger, config: Config) -> App:
            return App(logger, config)

        instance = container.resolve(App)
        assert isinstance(instance, App)
        assert isinstance(instance.logger, Logger)
        assert isinstance(instance.config, Config)


class TestDecoratorEdgeCases:
    """Test edge cases for decorator usage."""

    def test_decorator_preserves_class_attributes(self, container: Container) -> None:
        """Decorator should preserve class attributes and methods."""

        @container.register
        class MyService:
            class_attr = "value"

            def method(self) -> str:
                return "method_result"

        assert MyService.class_attr == "value"
        instance = container.resolve(MyService)
        assert instance.method() == "method_result"

    def test_decorator_preserves_function_attributes(self, container: Container) -> None:
        """Decorator should preserve function attributes."""

        class Service:
            pass

        @container.register
        def create_service() -> Service:
            """My factory docstring."""
            return Service()

        assert create_service.__name__ == "create_service"
        assert create_service.__doc__ == "My factory docstring."

    def test_decorator_with_generic_class(self, container: Container) -> None:
        """Decorator should work with generic classes."""
        from typing import Generic, TypeVar

        T = TypeVar("T")

        @container.register
        class Box(Generic[T]):
            def __init__(self) -> None:
                self.value: T | None = None

        instance = container.resolve(Box)
        assert isinstance(instance, Box)


class TestAsyncGeneratorFactoryDecorator:
    """Tests for async generator factory functions with decorator."""

    async def test_async_generator_factory_decorator(self, container: Container) -> None:
        """Async generator factory should work with decorator."""
        from collections.abc import AsyncGenerator

        cleanup_called = []

        class AsyncResource:
            pass

        @container.register(lifetime=Lifetime.SCOPED, scope="request")
        async def create_async_resource() -> AsyncGenerator[AsyncResource, None]:
            try:
                yield AsyncResource()
            finally:
                cleanup_called.append(True)

        async with container.enter_scope("request"):
            instance = await container.aresolve(AsyncResource)
            assert isinstance(instance, AsyncResource)
            assert cleanup_called == []

        assert cleanup_called == [True]


class TestSyncGeneratorFactoryDecorator:
    """Tests for sync generator factory functions with decorator."""

    def test_sync_generator_factory_decorator(self, container: Container) -> None:
        """Sync generator factory should work with decorator."""
        from collections.abc import Generator

        cleanup_called = []

        class SyncResource:
            pass

        @container.register(lifetime=Lifetime.SCOPED, scope="request")
        def create_sync_resource() -> Generator[SyncResource, None, None]:
            try:
                yield SyncResource()
            finally:
                cleanup_called.append(True)

        with container.enter_scope("request"):
            instance = container.resolve(SyncResource)
            assert isinstance(instance, SyncResource)
            assert cleanup_called == []

        assert cleanup_called == [True]


class TestStaticMethodDecorator:
    """Tests for using @container.register on staticmethod factories."""

    def test_staticmethod_bare_decorator(self, container: Container) -> None:
        """@staticmethod @container.register should work."""

        class Database:
            pass

        class Factories:
            @staticmethod
            @container.register
            def create_database() -> Database:
                return Database()

        instance = container.resolve(Database)
        assert isinstance(instance, Database)

    def test_staticmethod_parameterized_decorator(self, container: Container) -> None:
        """@staticmethod @container.register(lifetime=...) should work."""

        class Config:
            pass

        class Factories:
            @staticmethod
            @container.register(lifetime=Lifetime.SINGLETON)
            def create_config() -> Config:
                return Config()

        instance1 = container.resolve(Config)
        instance2 = container.resolve(Config)
        assert instance1 is instance2

    def test_staticmethod_with_interface_key(self, container: Container) -> None:
        """@staticmethod @container.register(Interface) should work."""

        class IService:
            pass

        class ServiceImpl(IService):
            pass

        class Factories:
            @staticmethod
            # Note: A non-default keyword arg needed to use type as decorator key vs bare registration
            @container.register(IService, lifetime=Lifetime.SINGLETON)
            def create_service() -> ServiceImpl:
                return ServiceImpl()

        instance = container.resolve(IService)
        assert isinstance(instance, ServiceImpl)

    def test_staticmethod_with_dependencies(self, container: Container) -> None:
        """Static method factory with dependencies should auto-inject."""

        class Logger:
            pass

        class Service:
            def __init__(self, logger: Logger) -> None:
                self.logger = logger

        class Factories:
            @staticmethod
            @container.register
            def create_service(logger: Logger) -> Service:
                return Service(logger)

        instance = container.resolve(Service)
        assert isinstance(instance, Service)
        assert isinstance(instance.logger, Logger)

    async def test_staticmethod_async_factory(self, container: Container) -> None:
        """@staticmethod async factory should work."""

        class AsyncService:
            pass

        class Factories:
            @staticmethod
            @container.register(lifetime=Lifetime.SINGLETON)
            async def create_async_service() -> AsyncService:
                return AsyncService()

        instance = await container.aresolve(AsyncService)
        assert isinstance(instance, AsyncService)

    def test_staticmethod_preserves_descriptor(self, container: Container) -> None:
        """Decorator should preserve the staticmethod descriptor."""

        class Service:
            pass

        class Factories:
            @staticmethod
            @container.register
            def create_service() -> Service:
                return Service()

        # The method should still be a staticmethod descriptor on the class
        assert isinstance(Factories.__dict__["create_service"], staticmethod)

        # Should be callable without self
        direct_result = Factories.create_service()
        assert isinstance(direct_result, Service)

    async def test_staticmethod_async_generator_factory(self, container: Container) -> None:
        """@staticmethod async generator factory should work with cleanup."""
        from collections.abc import AsyncGenerator

        cleanup_called = []

        class Resource:
            pass

        class Factories:
            @staticmethod
            @container.register(lifetime=Lifetime.SCOPED, scope="request")
            async def create_resource() -> AsyncGenerator[Resource, None]:
                try:
                    yield Resource()
                finally:
                    cleanup_called.append(True)

        async with container.enter_scope("request"):
            instance = await container.aresolve(Resource)
            assert isinstance(instance, Resource)
            assert cleanup_called == []

        assert cleanup_called == [True]


class TestStaticMethodWithoutReturnAnnotation:
    """Test for staticmethod without return annotation."""

    def test_staticmethod_without_return_annotation_raises(self, container: Container) -> None:
        """@staticmethod without return annotation should raise error."""
        from diwire.exceptions import DIWireDecoratorFactoryMissingReturnAnnotationError

        with pytest.raises(DIWireDecoratorFactoryMissingReturnAnnotationError):

            class Factories:
                @staticmethod
                @container.register
                def create_something():  # type: ignore[no-untyped-def]  # noqa: ANN205
                    return object()


class TestMethodDescriptorDecoratorOrder:
    """Tests for decorator order with staticmethod/classmethod."""

    def test_register_before_staticmethod_without_annotation_raises(
        self,
        container: Container,
    ) -> None:
        """@container.register @staticmethod without annotation should raise."""
        from diwire.exceptions import DIWireDecoratorFactoryMissingReturnAnnotationError

        with pytest.raises(DIWireDecoratorFactoryMissingReturnAnnotationError):

            class Factories:
                @container.register
                @staticmethod
                def create_something():  # type: ignore[no-untyped-def]  # noqa: ANN205
                    return object()

    def test_parameterized_register_before_staticmethod_without_annotation_raises(
        self,
        container: Container,
    ) -> None:
        """@container.register(lifetime=...) @staticmethod without annotation should raise."""
        from diwire.exceptions import DIWireDecoratorFactoryMissingReturnAnnotationError

        with pytest.raises(DIWireDecoratorFactoryMissingReturnAnnotationError):

            class Factories:
                @container.register(lifetime=Lifetime.SINGLETON)
                @staticmethod
                def create_something():  # type: ignore[no-untyped-def]  # noqa: ANN205
                    return object()

    def test_register_before_staticmethod(self, container: Container) -> None:
        """@container.register @staticmethod order should also work."""

        class Service:
            pass

        class Factories:
            @container.register
            @staticmethod
            def create_service() -> Service:
                return Service()

        instance = container.resolve(Service)
        assert isinstance(instance, Service)

    def test_parameterized_before_staticmethod(self, container: Container) -> None:
        """@container.register(lifetime=...) @staticmethod should work."""

        class Service:
            pass

        class Factories:
            @container.register(lifetime=Lifetime.SINGLETON)
            @staticmethod
            def create_service() -> Service:
                return Service()

        instance1 = container.resolve(Service)
        instance2 = container.resolve(Service)
        assert instance1 is instance2


class TestStringKeyRegistration:
    """Tests for registering services with string keys."""

    def test_string_key_factory_decorator(self, container: Container) -> None:
        """@container.register("key") on factory function should work."""
        from collections.abc import Callable
        from typing import cast

        class Service:
            value: str

            def __init__(self, value: str = "default") -> None:
                self.value = value

        decorator = cast(
            "Callable[[Callable[..., object]], Callable[..., object]]",
            container.register("my_service"),
        )

        def create_service() -> Service:
            return Service(value="from factory")

        decorator(create_service)

        result = container.resolve("my_service")
        assert isinstance(result, Service)
        assert result.value == "from factory"

    def test_string_key_class_decorator(self, container: Container) -> None:
        """@container.register("key") on class should work."""
        from collections.abc import Callable
        from typing import cast

        class ConfigService:
            name: str = "config"

        decorator = cast("Callable[[type], type]", container.register("config_service"))
        decorator(ConfigService)

        result = container.resolve("config_service")
        assert isinstance(result, ConfigService)
        assert result.name == "config"

    def test_string_key_with_lifetime(self, container: Container) -> None:
        """@container.register("key", lifetime=...) should work."""
        from collections.abc import Callable
        from typing import cast

        call_count = 0

        class Service:
            pass

        decorator = cast(
            "Callable[[Callable[..., object]], Callable[..., object]]",
            container.register("singleton_service", lifetime=Lifetime.SINGLETON),
        )

        def create_service() -> Service:
            nonlocal call_count
            call_count += 1
            return Service()

        decorator(create_service)

        result1 = container.resolve("singleton_service")
        result2 = container.resolve("singleton_service")
        assert result1 is result2
        assert call_count == 1

    def test_multiple_string_keys_same_class(self, container: Container) -> None:
        """Multiple string keys can point to same class."""
        from collections.abc import Callable
        from typing import cast

        class SharedService:
            pass

        decorator1 = cast("Callable[[type], type]", container.register("key1"))
        decorator2 = cast("Callable[[type], type]", container.register("key2"))
        decorator2(SharedService)
        decorator1(SharedService)

        result1 = container.resolve("key1")
        result2 = container.resolve("key2")
        assert isinstance(result1, SharedService)
        assert isinstance(result2, SharedService)

    def test_string_key_direct_registration(self, container: Container) -> None:
        """container.register("key", factory=...) direct call should work."""

        class Service:
            pass

        container.register("direct_key", factory=lambda: Service())
        result = container.resolve("direct_key")
        assert isinstance(result, Service)

    def test_string_key_instance_registration(self, container: Container) -> None:
        """container.register("key", instance=...) direct call should work."""

        class Service:
            value: str

            def __init__(self, value: str) -> None:
                self.value = value

        instance = Service(value="singleton")
        container.register("instance_key", instance=instance)
        result = container.resolve("instance_key")
        assert result is instance
        assert result.value == "singleton"
