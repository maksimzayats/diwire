"""Tests for _InjectedFunction wrapper class."""

from inspect import signature
from typing import Annotated

import pytest

from diwire.container import Container
from diwire.container_injection import _InjectedFunction
from diwire.exceptions import DIWireServiceNotRegisteredError
from diwire.types import Injected


class ServiceA:
    pass


class ServiceB:
    pass


class TestInjectedMetadata:
    def test_injected_preserves_function_docstring(self, container: Container) -> None:
        """Docstring should be preserved."""

        def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            """This is my docstring."""
            return service

        injected = container.resolve(my_func)

        assert injected.__doc__ == "This is my docstring."

    def test_injected_repr_format(self, container: Container) -> None:
        """Verify __repr__ output."""

        def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        injected = container.resolve(my_func)

        repr_str = repr(injected)
        assert repr_str.startswith("_InjectedFunction(")
        assert "my_func" in repr_str


class TestInjectedCallPatterns:
    def test_injected_with_positional_args(self, container: Container) -> None:
        """Call with *args."""

        def my_func(
            value: int,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[int, ServiceA]:
            return (value, service)

        injected = container.resolve(my_func)
        result = injected(42)

        assert result[0] == 42
        assert isinstance(result[1], ServiceA)

    def test_injected_positional_and_kwargs_mixed(self, container: Container) -> None:
        """Call with positional and kwargs mixed."""

        def my_func(
            a: int,
            b: str,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[int, str, ServiceA]:
            return (a, b, service)

        injected = container.resolve(my_func)
        result = injected(1, b="hello")

        assert result[0] == 1
        assert result[1] == "hello"
        assert isinstance(result[2], ServiceA)

    def test_injected_with_no_from_di_params(self, container: Container) -> None:
        """Function has no Injected markers."""

        def my_func(value: int) -> int:
            return value * 2

        injected = container.resolve(my_func)

        # Since no Injected params, injected should still work
        assert isinstance(injected, _InjectedFunction)
        result = injected(21)
        assert result == 42

    def test_injected_with_args_unpacking(self, container: Container) -> None:
        """Function has *args."""

        def my_func(
            *args: int,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[tuple[int, ...], ServiceA]:
            return (args, service)

        injected = container.resolve(my_func)
        result = injected(1, 2, 3)

        assert result[0] == (1, 2, 3)
        assert isinstance(result[1], ServiceA)

    def test_injected_with_kwargs_unpacking(self, container: Container) -> None:
        """Function has **kwargs."""

        def my_func(
            service: Annotated[ServiceA, Injected()],
            **kwargs: str,
        ) -> tuple[ServiceA, dict[str, str]]:
            return (service, kwargs)

        injected = container.resolve(my_func)
        result = injected(a="hello", b="world")

        assert isinstance(result[0], ServiceA)
        assert result[1] == {"a": "hello", "b": "world"}

    def test_injected_with_args_and_kwargs(self, container: Container) -> None:
        """Function has both *args and **kwargs."""

        def my_func(
            *args: int,
            service: Annotated[ServiceA, Injected()],
            **kwargs: str,
        ) -> tuple[tuple[int, ...], ServiceA, dict[str, str]]:
            return (args, service, kwargs)

        injected = container.resolve(my_func)
        result = injected(1, 2, name="test")

        assert result[0] == (1, 2)
        assert isinstance(result[1], ServiceA)
        assert result[2] == {"name": "test"}

    def test_injected_with_default_arguments(self, container: Container) -> None:
        """Param defaults preserved for non-injected params."""

        def my_func(
            service: Annotated[ServiceA, Injected()],
            value: int = 10,
        ) -> tuple[int, ServiceA]:
            return (value, service)

        injected = container.resolve(my_func)
        result = injected()

        assert result[0] == 10
        assert isinstance(result[1], ServiceA)

    def test_injected_with_keyword_only_args(self, container: Container) -> None:
        """Function has keyword-only args."""

        def my_func(
            *,
            value: int,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[int, ServiceA]:
            return (value, service)

        injected = container.resolve(my_func)
        result = injected(value=42)

        assert result[0] == 42
        assert isinstance(result[1], ServiceA)

    def test_injected_with_positional_only_args(self, container: Container) -> None:
        """Function has positional-only args (Python 3.8+)."""

        def my_func(
            value: int,
            /,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[int, ServiceA]:
            return (value, service)

        injected = container.resolve(my_func)
        result = injected(42)

        assert result[0] == 42
        assert isinstance(result[1], ServiceA)


class TestInjectedSpecialMethods:
    def test_injected_with_staticmethod(self, container: Container) -> None:
        """Static method can be injected (when passed as function)."""

        class MyClass:
            @staticmethod
            def my_method(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

        # Extract the underlying function from staticmethod
        static_func = MyClass.__dict__["my_method"].__func__
        injected = container.resolve(static_func)
        result = injected()

        assert isinstance(result, ServiceA)

    def test_injected_with_lambda(self, container: Container) -> None:
        """Lambda works because it falls back to repr(func) for name."""
        # Lambdas don't support type annotations, so no DI params will be detected
        my_lambda = lambda x: x  # noqa: E731
        injected = container.resolve(my_lambda)

        assert isinstance(injected, _InjectedFunction)
        result = injected(42)
        assert result == 42


class TestInjectedSignature:
    def test_signature_preserves_non_injected_defaults(
        self,
        container: Container,
    ) -> None:
        """Non-injected params preserve defaults in signature."""

        def my_func(
            service: Annotated[ServiceA, Injected()],
            value: int = 100,
        ) -> int:
            return value

        injected = container.resolve(my_func)
        sig = signature(injected)

        assert "value" in sig.parameters
        assert sig.parameters["value"].default == 100

    def test_signature_preserves_annotations(self, container: Container) -> None:
        """Non-injected params preserve annotations."""

        def my_func(
            value: int,
            service: Annotated[ServiceA, Injected()],
        ) -> int:
            return value

        injected = container.resolve(my_func)
        sig = signature(injected)

        assert sig.parameters["value"].annotation is int

    def test_signature_with_all_params_injected(self, container: Container) -> None:
        """Empty signature when all params are injected."""

        def my_func(
            service_a: Annotated[ServiceA, Injected()],
            service_b: Annotated[ServiceB, Injected()],
        ) -> tuple[ServiceA, ServiceB]:
            return (service_a, service_b)

        injected = container.resolve(my_func)
        sig = signature(injected)

        assert len(sig.parameters) == 0


class TestInjectedDependencyResolution:
    def test_injected_when_dependency_resolution_fails(
        self,
        container_no_autoregister: Container,
    ) -> None:
        """Resolution fails when dependency not registered."""

        class UnregisteredService:
            pass

        def my_func(
            service: Annotated[UnregisteredService, Injected()],
        ) -> UnregisteredService:
            return service

        injected = container_no_autoregister.resolve(my_func)

        with pytest.raises(DIWireServiceNotRegisteredError):
            # Error occurs when calling, not when resolving the function
            injected()

    def test_injected_multiple_from_di_params(self, container: Container) -> None:
        """Multiple Injected params resolved."""

        def my_func(
            a: Annotated[ServiceA, Injected()],
            b: Annotated[ServiceB, Injected()],
        ) -> tuple[ServiceA, ServiceB]:
            return (a, b)

        injected = container.resolve(my_func)
        result = injected()

        assert isinstance(result[0], ServiceA)
        assert isinstance(result[1], ServiceB)

    def test_injected_transient_creates_fresh_each_call(
        self,
        container: Container,
    ) -> None:
        """Transient dependencies are fresh on each call."""

        def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        injected = container.resolve(my_func)

        result1 = injected()
        result2 = injected()

        assert result1 is not result2

    def test_injected_singleton_reuses_same_instance(
        self,
        container_singleton: Container,
    ) -> None:
        """Singleton dependencies are reused."""

        def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        injected = container_singleton.resolve(my_func)

        result1 = injected()
        result2 = injected()

        assert result1 is result2


class TestAsyncInjectedMetadata:
    """Tests for AsyncInjected metadata preservation."""

    async def test_async_injected_preserves_docstring(self, container: Container) -> None:
        """AsyncInjected preserves function docstring."""
        from diwire.container_injection import _AsyncInjectedFunction

        async def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            """This is my async docstring."""
            return service

        injected = await container.aresolve(my_func)

        assert isinstance(injected, _AsyncInjectedFunction)
        assert injected.__doc__ == "This is my async docstring."

    async def test_async_injected_repr_format(self, container: Container) -> None:
        """AsyncInjected has correct __repr__ format."""

        async def my_async_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        injected = await container.aresolve(my_async_func)

        repr_str = repr(injected)
        assert repr_str.startswith("_AsyncInjectedFunction(")
        assert "my_async_func" in repr_str


class TestAsyncInjectedCallPatterns:
    """Tests for AsyncInjected call patterns."""

    async def test_async_injected_with_positional_args(
        self,
        container: Container,
    ) -> None:
        """AsyncInjected call with positional args."""

        async def my_func(
            value: int,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[int, ServiceA]:
            return (value, service)

        injected = await container.aresolve(my_func)
        result = await injected(42)

        assert result[0] == 42
        assert isinstance(result[1], ServiceA)

    async def test_async_injected_with_kwargs(self, container: Container) -> None:
        """AsyncInjected call with kwargs."""

        async def my_func(
            a: int,
            b: str,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[int, str, ServiceA]:
            return (a, b, service)

        injected = await container.aresolve(my_func)
        result = await injected(1, b="hello")

        assert result[0] == 1
        assert result[1] == "hello"
        assert isinstance(result[2], ServiceA)

    async def test_async_injected_with_mixed_patterns(
        self,
        container: Container,
    ) -> None:
        """AsyncInjected call with mixed positional, kwargs, and injected params."""

        async def my_func(
            pos: int,
            *args: int,
            service: Annotated[ServiceA, Injected()],
            **kwargs: str,
        ) -> tuple[int, tuple[int, ...], ServiceA, dict[str, str]]:
            return (pos, args, service, kwargs)

        injected = await container.aresolve(my_func)
        result = await injected(1, 2, 3, name="test")

        assert result[0] == 1
        assert result[1] == (2, 3)
        assert isinstance(result[2], ServiceA)
        assert result[3] == {"name": "test"}


class TestInjectedMethodDecoration:
    """Tests for decorating instance methods, class methods, and properties."""

    def test_instance_method_decoration(self, container: Container) -> None:
        """Instance method decorated with container.resolve() binds self correctly."""

        class MyController:
            def __init__(self, prefix: str) -> None:
                self.prefix = prefix

        # Define handler after class to avoid forward reference
        def handler_impl(
            self: MyController,
            service: Annotated[ServiceA, Injected()],
        ) -> tuple[str, ServiceA]:
            return (self.prefix, service)

        # Assign the resolved handler to the class
        MyController.handler = container.resolve(handler_impl)  # type: ignore[attr-defined, unresolved-attribute]

        controller = MyController("/api")
        result = controller.handler()  # type: ignore[attr-defined, unresolved-attribute]

        assert result[0] == "/api"
        assert isinstance(result[1], ServiceA)

    def test_class_at_definition_time_instance_method(
        self,
        container: Container,
    ) -> None:
        """Instance method defined with decorator at class definition time."""

        class MyService:
            def __init__(self, name: str) -> None:
                self.name = name

            @container.resolve()
            def process(
                self,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[str, ServiceA]:
                return (self.name, service)

        instance = MyService("test-service")
        result = instance.process()

        assert result[0] == "test-service"
        assert isinstance(result[1], ServiceA)

    def test_static_method_with_di(self, container: Container) -> None:
        """Static method can be resolved (no self binding needed)."""

        class MyClass:
            @staticmethod
            @container.resolve()
            def static_handler(
                service: Annotated[ServiceA, Injected()],
            ) -> ServiceA:
                return service

        result = MyClass.static_handler()
        assert isinstance(result, ServiceA)

        # Also works from instance
        obj = MyClass()
        result2 = obj.static_handler()
        assert isinstance(result2, ServiceA)

    def test_class_method_decoration(self, container: Container) -> None:
        """Class method decorated with container.resolve() binds cls correctly."""

        class MyFactory:
            class_name = "MyFactory"

            @classmethod
            @container.resolve()
            def create(
                cls,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[str, ServiceA]:
                return (cls.class_name, service)

        result = MyFactory.create()

        assert result[0] == "MyFactory"
        assert isinstance(result[1], ServiceA)

    def test_scoped_instance_method_decoration(self, container: Container) -> None:
        """ScopedInjected with instance method binds self correctly."""
        from diwire.types import Lifetime

        class ScopedService:
            pass

        container.register(
            ScopedService,
            lifetime=Lifetime.SCOPED,
            scope="request",
        )

        class MyHandler:
            def __init__(self, name: str) -> None:
                self.name = name

            @container.resolve(scope="request")
            def handle(
                self,
                service: Annotated[ScopedService, Injected()],
            ) -> tuple[str, ScopedService]:
                return (self.name, service)

        handler = MyHandler("handler-1")

        with container.enter_scope("request"):
            result = handler.handle()
            assert result[0] == "handler-1"
            assert isinstance(result[1], ScopedService)

    async def test_async_instance_method_decoration(
        self,
        container: Container,
    ) -> None:
        """AsyncInjected with instance method binds self correctly."""

        class AsyncController:
            def __init__(self, path: str) -> None:
                self.path = path

            @container.resolve()
            async def fetch(
                self,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[str, ServiceA]:
                return (self.path, service)

        controller = AsyncController("/data")
        result = await controller.fetch()

        assert result[0] == "/data"
        assert isinstance(result[1], ServiceA)

    async def test_async_scoped_instance_method_decoration(
        self,
        container: Container,
    ) -> None:
        """AsyncScopedInjected with instance method binds self correctly."""
        from diwire.types import Lifetime

        class AsyncScopedService:
            pass

        container.register(
            AsyncScopedService,
            lifetime=Lifetime.SCOPED,
            scope="async-request",
        )

        class AsyncHandler:
            def __init__(self, endpoint: str) -> None:
                self.endpoint = endpoint

            @container.resolve(scope="async-request")
            async def process(
                self,
                service: Annotated[AsyncScopedService, Injected()],
            ) -> tuple[str, AsyncScopedService]:
                return (self.endpoint, service)

        handler = AsyncHandler("/api/async")

        async with container.enter_scope("async-request"):
            result = await handler.process()
            assert result[0] == "/api/async"
            assert isinstance(result[1], AsyncScopedService)

    def test_multiple_instances_share_singleton(
        self,
        container_singleton: Container,
    ) -> None:
        """Verify singleton behavior across multiple instances."""

        class Controller:
            def __init__(self, name: str) -> None:
                self.name = name

            @container_singleton.resolve()
            def get_service(
                self,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[str, ServiceA]:
                return (self.name, service)

        controller1 = Controller("first")
        controller2 = Controller("second")

        result1 = controller1.get_service()
        result2 = controller2.get_service()

        # Names should differ (different instances)
        assert result1[0] == "first"
        assert result2[0] == "second"

        # But singleton service should be the same
        assert result1[1] is result2[1]

    def test_method_accesses_instance_attributes(
        self,
        container: Container,
    ) -> None:
        """Verify self.attribute access works correctly."""

        class DataProcessor:
            def __init__(self, items: list[str]) -> None:
                self.items = items
                self.processed_count = 0

            @container.resolve()
            def process_all(
                self,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[list[str], int, ServiceA]:
                self.processed_count = len(self.items)
                return (self.items, self.processed_count, service)

        processor = DataProcessor(["a", "b", "c"])
        result = processor.process_all()

        assert result[0] == ["a", "b", "c"]
        assert result[1] == 3
        assert processor.processed_count == 3
        assert isinstance(result[2], ServiceA)

    def test_descriptor_returns_self_when_accessed_on_class(
        self,
        container: Container,
    ) -> None:
        """Accessing the method on the class returns the Injected wrapper."""

        class MyClass:
            @container.resolve()
            def method(
                self,
                service: Annotated[ServiceA, Injected()],
            ) -> ServiceA:
                return service

        # Accessing on class should return the Injected wrapper itself
        assert isinstance(MyClass.method, _InjectedFunction)

    def test_property_with_di(self, container: Container) -> None:
        """Property getter can use DI to resolve dependencies."""

        class Config:
            def __init__(self, base_url: str) -> None:
                self.base_url = base_url

            @property
            def service(self) -> ServiceA:
                return self._get_service()

            @container.resolve()
            def _get_service(
                self,
                service: Annotated[ServiceA, Injected()],
            ) -> ServiceA:
                return service

        config = Config("http://example.com")
        result = config.service

        assert isinstance(result, ServiceA)

    def test_property_combining_instance_state_and_di(
        self,
        container: Container,
    ) -> None:
        """Property can combine instance state with injected dependencies."""

        class DataService:
            def __init__(self, prefix: str) -> None:
                self.prefix = prefix

            @property
            def formatted_data(self) -> tuple[str, ServiceA]:
                return self._get_formatted_data()

            @container.resolve()
            def _get_formatted_data(
                self,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[str, ServiceA]:
                return (f"{self.prefix}-data", service)

        data_service = DataService("test")
        result = data_service.formatted_data

        assert result[0] == "test-data"
        assert isinstance(result[1], ServiceA)

    def test_cached_property_pattern_with_di(
        self,
        container_singleton: Container,
    ) -> None:
        """Cached property pattern with DI - singleton dependency is reused."""

        class LazyService:
            def __init__(self) -> None:
                self._cached_service: ServiceA | None = None

            @property
            def service(self) -> ServiceA:
                if self._cached_service is None:
                    self._cached_service = self._fetch_service()
                return self._cached_service

            @container_singleton.resolve()
            def _fetch_service(
                self,
                service: Annotated[ServiceA, Injected()],
            ) -> ServiceA:
                return service

        lazy = LazyService()

        # First access
        service1 = lazy.service
        # Second access (from cache)
        service2 = lazy.service

        assert service1 is service2
        assert isinstance(service1, ServiceA)

    async def test_async_property_pattern_with_di(
        self,
        container: Container,
    ) -> None:
        """Async method used as property-like accessor with DI."""

        class AsyncDataSource:
            def __init__(self, source_id: str) -> None:
                self.source_id = source_id

            @container.resolve()
            async def get_data(
                self,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[str, ServiceA]:
                return (f"data-{self.source_id}", service)

        source = AsyncDataSource("abc123")
        result = await source.get_data()

        assert result[0] == "data-abc123"
        assert isinstance(result[1], ServiceA)

    def test_property_with_scoped_di(self, container: Container) -> None:
        """Property using scoped DI within a scope context."""
        from diwire.types import Lifetime

        class ScopedDep:
            pass

        container.register(ScopedDep, lifetime=Lifetime.SCOPED, scope="request")

        class RequestHandler:
            def __init__(self, path: str) -> None:
                self.path = path

            @property
            def response(self) -> tuple[str, ScopedDep]:
                return self._build_response()

            @container.resolve(scope="request")
            def _build_response(
                self,
                dep: Annotated[ScopedDep, Injected()],
            ) -> tuple[str, ScopedDep]:
                return (self.path, dep)

        handler = RequestHandler("/api/users")

        with container.enter_scope("request"):
            result = handler.response
            assert result[0] == "/api/users"
            assert isinstance(result[1], ScopedDep)

    def test_property_and_resolve_decorators_combined(
        self,
        container: Container,
    ) -> None:
        """Property and resolve decorators can be combined directly."""

        class ServiceProvider:
            def __init__(self, name: str) -> None:
                self.name = name

            @property
            @container.resolve()
            def service(
                self,
                svc: Annotated[ServiceA, Injected()],
            ) -> tuple[str, ServiceA]:
                return (self.name, svc)

        provider = ServiceProvider("my-provider")
        result = provider.service

        assert result[0] == "my-provider"
        assert isinstance(result[1], ServiceA)

    def test_property_and_resolve_with_singleton(
        self,
        container_singleton: Container,
    ) -> None:
        """Property with resolve returns same singleton on multiple accesses."""

        class SingletonHolder:
            @property
            @container_singleton.resolve()
            def service(
                self,
                svc: Annotated[ServiceA, Injected()],
            ) -> ServiceA:
                return svc

        holder = SingletonHolder()

        # Multiple property accesses should return the same singleton
        service1 = holder.service
        service2 = holder.service

        assert service1 is service2
        assert isinstance(service1, ServiceA)

    def test_property_and_resolve_accesses_self(
        self,
        container: Container,
    ) -> None:
        """Property with resolve can access self attributes."""

        class Counter:
            def __init__(self) -> None:
                self.count = 0

            @property
            @container.resolve()
            def incremented(
                self,
                svc: Annotated[ServiceA, Injected()],
            ) -> tuple[int, ServiceA]:
                self.count += 1
                return (self.count, svc)

        counter = Counter()

        result1 = counter.incremented
        assert result1[0] == 1

        result2 = counter.incremented
        assert result2[0] == 2

        assert counter.count == 2

    async def test_async_property_pattern_combined_decorators(
        self,
        container: Container,
    ) -> None:
        """Async method with property-like pattern using combined decorators."""

        class AsyncService:
            def __init__(self, id_: str) -> None:
                self.id_ = id_

            # Note: Can't use @property with async, but can use resolve directly
            @container.resolve()
            async def fetch_data(
                self,
                svc: Annotated[ServiceA, Injected()],
            ) -> tuple[str, ServiceA]:
                return (f"data-{self.id_}", svc)

        service = AsyncService("123")
        result = await service.fetch_data()

        assert result[0] == "data-123"
        assert isinstance(result[1], ServiceA)
