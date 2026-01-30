import uuid
from collections.abc import AsyncGenerator, Callable, Generator
from dataclasses import dataclass, field
from functools import partial
from inspect import signature
from typing import Annotated

import pytest

from diwire.compiled_providers import ScopedSingletonArgsProvider
from diwire.container import Container
from diwire.container_helpers import _is_async_factory
from diwire.container_injection import (
    _AsyncInjectedFunction,
    _AsyncScopedInjectedFunction,
    _InjectedFunction,
    _ScopedInjectedFunction,
)
from diwire.container_scopes import _current_scope, _ScopeId
from diwire.dependencies import DependenciesExtractor
from diwire.exceptions import (
    DIWireCircularDependencyError,
    DIWireGeneratorFactoryDidNotYieldError,
    DIWireGeneratorFactoryUnsupportedLifetimeError,
    DIWireIgnoredServiceError,
    DIWireMissingDependenciesError,
    DIWireScopeMismatchError,
)
from diwire.registry import Registration
from diwire.service_key import ServiceKey
from diwire.types import Injected, Lifetime


# Module-level classes for circular dependency tests
# These need to be at module level for forward reference resolution
class _CircularServiceA:
    def __init__(self, b: "_CircularServiceB") -> None:
        self.b = b


class _CircularServiceB:
    def __init__(self, a: _CircularServiceA) -> None:
        self.a = a


# Module-level classes for async circular dependency test
class _AsyncCircularA:
    def __init__(self, b: "_AsyncCircularB") -> None:
        self.b = b


class _AsyncCircularB:
    def __init__(self, a: _AsyncCircularA) -> None:
        self.a = a


def test_auto_registers_class(container: Container) -> None:
    class ServiceA:
        pass

    instance = container.resolve(ServiceA)
    assert isinstance(instance, ServiceA)


def test_auto_registers_class_with_dependencies(container: Container) -> None:
    class ServiceA:
        pass

    class ServiceB:
        def __init__(self, service_a: ServiceA) -> None:
            self.service_a = service_a

    instance_b = container.resolve(ServiceB)
    assert isinstance(instance_b, ServiceB)
    assert isinstance(instance_b.service_a, ServiceA)


def test_auto_registers_kind_singleton(container_singleton: Container) -> None:
    class ServiceA:
        pass

    instance1 = container_singleton.resolve(ServiceA)
    instance2 = container_singleton.resolve(ServiceA)
    assert instance1 is instance2


def test_auto_registers_kind_transient(container: Container) -> None:
    class ServiceA:
        pass

    instance1 = container.resolve(ServiceA)
    instance2 = container.resolve(ServiceA)
    assert instance1 is not instance2


def test_does_not_auto_register_ignored_class(container: Container) -> None:
    class IgnoredClass:
        pass

    container._autoregister_ignores.add(IgnoredClass)

    with pytest.raises(DIWireIgnoredServiceError):
        container.resolve(IgnoredClass)


def test_resolve_function_returns_injected(container: Container) -> None:
    class ServiceA:
        pass

    def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
        return service

    injected = container.resolve(my_func)
    assert isinstance(injected, _InjectedFunction)


def test_injected_resolves_transient_deps_on_each_call(container: Container) -> None:
    """Transient dependencies should be created fresh on each function call."""

    class ServiceA:
        pass

    def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
        return service

    injected = container.resolve(my_func)

    result1 = injected()
    result2 = injected()

    assert isinstance(result1, ServiceA)
    assert isinstance(result2, ServiceA)
    assert result1 is not result2  # Different instances on each call


def test_injected_resolves_singleton_deps_once(container_singleton: Container) -> None:
    """Singleton dependencies should be the same instance on each call."""

    class ServiceA:
        pass

    def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
        return service

    injected = container_singleton.resolve(my_func)

    result1 = injected()
    result2 = injected()

    assert isinstance(result1, ServiceA)
    assert result1 is result2  # Same instance on each call


def test_injected_allows_explicit_kwargs_override(container: Container) -> None:
    """Explicit kwargs should override resolved dependencies."""

    class ServiceA:
        pass

    def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
        return service

    injected = container.resolve(my_func)
    explicit_service = ServiceA()

    result = injected(service=explicit_service)

    assert result is explicit_service


def test_injected_preserves_function_name(container: Container) -> None:
    class ServiceA:
        pass

    def my_named_function(service: Annotated[ServiceA, Injected()]) -> ServiceA:
        return service

    injected = container.resolve(my_named_function)

    assert injected.__name__ == "my_named_function"
    assert injected.__wrapped__ is my_named_function


def test_injected_signature_excludes_injected_params(container: Container) -> None:
    """Signature should only show non-injected (non-Injected) parameters."""

    class ServiceA:
        pass

    def my_func(value: int, service: Annotated[ServiceA, Injected()]) -> int:
        return value

    injected = container.resolve(my_func)
    sig = signature(injected)

    # 'service' is marked with Injected, should be removed from signature
    # 'value' is not marked with Injected, should remain
    param_names = list(sig.parameters.keys())
    assert param_names == ["value"]
    assert "service" not in param_names


def test_resolve_dataclass_injects_from_di_field(container: Container) -> None:
    class ServiceA:
        pass

    @dataclass
    class ServiceB:
        service_a: Annotated[ServiceA, Injected()]

    service_b = container.resolve(ServiceB)
    assert isinstance(service_b.service_a, ServiceA)


class TestIgnoredTypesWithDefaults:
    """Tests for resolving classes with ignored types that have default values."""

    def test_resolve_class_with_ignored_type_and_default(
        self,
        container: Container,
    ) -> None:
        """str with default should resolve successfully."""

        class MyClass:
            def __init__(self, name: str = "default_name") -> None:
                self.name = name

        instance = container.resolve(MyClass)
        assert isinstance(instance, MyClass)
        assert instance.name == "default_name"

    def test_resolve_dataclass_with_default_factory(
        self,
        container: Container,
    ) -> None:
        """Dataclass with field(default_factory=...) should work."""

        @dataclass
        class Session:
            id: str = field(default_factory=lambda: str(uuid.uuid4()))

        instance = container.resolve(Session)
        assert isinstance(instance, Session)
        assert isinstance(instance.id, str)
        assert len(instance.id) > 0

    def test_resolve_class_with_ignored_type_no_default_fails(
        self,
        container: Container,
    ) -> None:
        """str without default should fail with DIWireMissingDependenciesError."""

        class MyClass:
            def __init__(self, name: str) -> None:
                self.name = name

        with pytest.raises(DIWireMissingDependenciesError):
            container.resolve(MyClass)

    def test_resolve_mixed_params_with_defaults(
        self,
        container: Container,
    ) -> None:
        """Mix of params: some with defaults, some without."""

        class ServiceA:
            pass

        @dataclass
        class MyClass:
            service: ServiceA  # Should be resolved from container
            name: str = "default"  # Ignored type with default, should use default
            count: int = 42  # Ignored type with default, should use default

        instance = container.resolve(MyClass)
        assert isinstance(instance, MyClass)
        assert isinstance(instance.service, ServiceA)
        assert instance.name == "default"
        assert instance.count == 42

    def test_resolve_dataclass_with_default_value(
        self,
        container: Container,
    ) -> None:
        """Dataclass with field default (not factory) should work."""

        @dataclass
        class Config:
            timeout: int = 30
            retries: int = 3

        instance = container.resolve(Config)
        assert isinstance(instance, Config)
        assert instance.timeout == 30
        assert instance.retries == 3

    def test_resolve_non_ignored_type_without_default_fails(
        self,
        container: Container,
    ) -> None:
        """Non-ignored type without default and not resolvable should fail."""

        class UnregisteredService:
            pass

        class MyClass:
            def __init__(self, service: UnregisteredService) -> None:
                self.service = service

        # Add UnregisteredService to ignores to simulate unresolvable
        container._autoregister_ignores.add(UnregisteredService)

        with pytest.raises(DIWireMissingDependenciesError):
            container.resolve(MyClass)

    def test_resolve_non_ignored_type_with_default_uses_default_on_failure(
        self,
        container: Container,
    ) -> None:
        """Non-ignored type that fails resolution but has default should use default."""

        class UnregisteredService:
            pass

        default_service = UnregisteredService()

        class MyClass:
            def __init__(self, service: UnregisteredService = default_service) -> None:
                self.service = service

        # Add to ignores to make resolution fail
        container._autoregister_ignores.add(UnregisteredService)

        instance = container.resolve(MyClass)
        assert isinstance(instance, MyClass)
        assert instance.service is default_service


class TestAsyncResolveFunction:
    """Tests for aresolve() on sync functions."""

    @pytest.mark.asyncio
    async def test_aresolve_on_sync_function_returns_injected(
        self,
        container: Container,
    ) -> None:
        """aresolve() on sync function returns Injected (not AsyncInjected)."""

        class ServiceA:
            pass

        def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        injected = await container.aresolve(my_func)

        # Should be Injected, not AsyncInjected
        assert isinstance(injected, _InjectedFunction)
        # Verify it's callable and works
        result = injected()
        assert isinstance(result, ServiceA)


class TestAsyncCallableClassFactory:
    """Tests for _is_async_factory with callable classes."""

    def test_is_async_factory_with_async_callable_class(self) -> None:
        """Test _is_async_factory() detects callable class with async __call__."""

        class AsyncCallableFactory:
            async def __call__(self) -> str:
                return "async result"

        class SyncCallableFactory:
            def __call__(self) -> str:
                return "sync result"

        # Class with async __call__ should be detected as async factory
        assert _is_async_factory(AsyncCallableFactory) is True

        # Class with sync __call__ should not be detected as async factory
        assert _is_async_factory(SyncCallableFactory) is False

        # Regular class without __call__ should not be async
        class RegularClass:
            pass

        assert _is_async_factory(RegularClass) is False

    def test_is_async_factory_with_async_callable_instance(self) -> None:
        """Test _is_async_factory() detects callable instance with async __call__."""

        class AsyncCallableFactory:
            async def __call__(self) -> str:
                return "async result"

        class SyncCallableFactory:
            def __call__(self) -> str:
                return "sync result"

        # Instance with async __call__ should be detected as async factory
        assert _is_async_factory(AsyncCallableFactory()) is True

        # Instance with sync __call__ should not be detected as async factory
        assert _is_async_factory(SyncCallableFactory()) is False

    def test_is_async_factory_with_async_gen_callable_instance(self) -> None:
        """Test _is_async_factory() detects callable instance with async generator __call__."""

        class AsyncGenCallableFactory:
            async def __call__(self) -> AsyncGenerator[str, None]:
                yield "async gen result"

        # Instance with async generator __call__ should be detected as async
        assert _is_async_factory(AsyncGenCallableFactory()) is True

    def test_is_async_factory_with_partial_wrapped_callable(self) -> None:
        """Test _is_async_factory() detects async partials via wrapped function."""

        async def async_factory() -> str:
            return "async result"

        def sync_factory() -> str:
            return "sync result"

        assert _is_async_factory(partial(async_factory)) is True
        assert _is_async_factory(partial(sync_factory)) is False

    def test_is_async_factory_with_wrapped_func_attribute(self) -> None:
        """Test _is_async_factory() checks wrapped func before __call__."""

        async def async_factory() -> str:
            return "async result"

        def sync_factory() -> str:
            return "sync result"

        class FuncWrapper:
            def __init__(self, func: Callable[[], object]) -> None:
                self.func = func

            def __call__(self) -> str:
                return "sync result"

        assert _is_async_factory(FuncWrapper(async_factory)) is True
        assert _is_async_factory(FuncWrapper(sync_factory)) is False

    def test_registration_detects_async_callable_instance_factory(self) -> None:
        """Test that registration correctly detects async callable instance factory."""

        class ServiceA:
            pass

        class AsyncServiceFactory:
            async def __call__(self) -> ServiceA:
                return ServiceA()

        class SyncServiceFactory:
            def __call__(self) -> ServiceA:
                return ServiceA()

        container = Container(auto_compile=False)

        # Register with async callable instance - should detect is_async=True
        container.register(ServiceA, factory=AsyncServiceFactory(), lifetime=Lifetime.TRANSIENT)
        registration = container._registry.get(ServiceKey.from_value(ServiceA))
        assert registration is not None
        assert registration.is_async is True

        # Register with sync callable instance - should detect is_async=False
        container.register(ServiceA, factory=SyncServiceFactory(), lifetime=Lifetime.TRANSIENT)
        registration = container._registry.get(ServiceKey.from_value(ServiceA))
        assert registration is not None
        assert registration.is_async is False


class TestDescriptorProtocol:
    """Tests for descriptor protocol __get__ methods returning self when obj is None."""

    def test_injected_get_returns_self_when_obj_none(
        self,
        container: Container,
    ) -> None:
        """_InjectedFunction descriptor returns self when accessed on class."""

        class ServiceA:
            pass

        def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        service_key = ServiceKey.from_value(my_func)
        deps_extractor = DependenciesExtractor()

        injected_func = _InjectedFunction(
            func=my_func,
            container=container,
            dependencies_extractor=deps_extractor,
            service_key=service_key,
        )

        # When obj is None, __get__ should return self
        result = injected_func.__get__(None, type(injected_func))
        assert result is injected_func

    def test_scoped_injected_get_returns_self_when_obj_none(
        self,
        container: Container,
    ) -> None:
        """_ScopedInjectedFunction descriptor returns self when accessed on class."""

        class ServiceA:
            pass

        def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        service_key = ServiceKey.from_value(my_func)
        deps_extractor = DependenciesExtractor()

        scoped_injected = _ScopedInjectedFunction(
            func=my_func,
            container=container,
            dependencies_extractor=deps_extractor,
            service_key=service_key,
            scope_name="request",
        )

        # When obj is None, __get__ should return self
        result = scoped_injected.__get__(None, type(scoped_injected))
        assert result is scoped_injected

    def test_async_injected_get_returns_self_when_obj_none(
        self,
        container: Container,
    ) -> None:
        """_AsyncInjectedFunction descriptor returns self when accessed on class."""

        class ServiceA:
            pass

        async def my_async_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        service_key = ServiceKey.from_value(my_async_func)
        deps_extractor = DependenciesExtractor()

        async_injected = _AsyncInjectedFunction(
            func=my_async_func,
            container=container,
            dependencies_extractor=deps_extractor,
            service_key=service_key,
        )

        # When obj is None, __get__ should return self
        result = async_injected.__get__(None, type(async_injected))
        assert result is async_injected

    def test_async_scoped_injected_get_returns_self_when_obj_none(
        self,
        container: Container,
    ) -> None:
        """_AsyncScopedInjectedFunction descriptor returns self when accessed on class."""

        class ServiceA:
            pass

        async def my_async_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        service_key = ServiceKey.from_value(my_async_func)
        deps_extractor = DependenciesExtractor()

        async_scoped_injected = _AsyncScopedInjectedFunction(
            func=my_async_func,
            container=container,
            dependencies_extractor=deps_extractor,
            service_key=service_key,
            scope_name="request",
        )

        # When obj is None, __get__ should return self
        result = async_scoped_injected.__get__(None, type(async_scoped_injected))
        assert result is async_scoped_injected


class TestCompilationEdgeCases:
    """Tests for compilation edge cases."""

    def test_async_deps_cache_diwire_error_continues(self) -> None:
        """DIWireError during async deps cache building is caught gracefully."""
        container = Container(autoregister=False, auto_compile=False)

        class ServiceA:
            pass

        class ServiceB:
            def __init__(self, a: ServiceA) -> None:
                self.a = a

        # Register ServiceB but not ServiceA - this will cause DIWireError during deps extraction
        container.register(ServiceB, lifetime=Lifetime.TRANSIENT)

        # compile() should handle the error gracefully
        container.compile()

        # Container should be compiled
        assert container._is_compiled is True

    def test_factory_provider_chain_compilation(self) -> None:
        """Factory registration compiles with provider chain."""

        class ServiceA:
            pass

        class ServiceAFactory:
            def __call__(self) -> ServiceA:
                return ServiceA()

        container = Container(auto_compile=False)
        container.register(ServiceA, factory=ServiceAFactory, lifetime=Lifetime.TRANSIENT)
        container.compile()

        # Should have compiled the factory provider chain
        service_key = ServiceKey.from_value(ServiceA)
        assert service_key in container._compiled_providers

    def test_non_type_service_key_returns_none_during_compilation(self) -> None:
        """Non-type service keys return None during compilation."""
        container = Container(auto_compile=False)

        # Register a string key (non-type) - should skip during compilation
        string_key = ServiceKey(value="string_key", component=None)
        registration = Registration(
            service_key=string_key,
            lifetime=Lifetime.TRANSIENT,
        )
        container._registry[string_key] = registration

        container.compile()

        # String key should not have a compiled provider
        assert string_key not in container._compiled_providers

    def test_missing_required_ignored_dependency_during_compilation(self) -> None:
        """Missing required ignored dependency returns None during compilation."""
        container = Container(autoregister=False, auto_compile=False)

        class ServiceWithStr:
            def __init__(self, name: str) -> None:  # str is ignored, no default
                self.name = name

        container.register(ServiceWithStr, lifetime=Lifetime.TRANSIENT)
        container.compile()

        # ServiceWithStr should not have a compiled provider because str has no default
        service_key = ServiceKey.from_value(ServiceWithStr)
        assert service_key not in container._compiled_providers

    def test_auto_registration_provider_compilation_fallback(self) -> None:
        """Auto-registration compiles providers during resolution."""
        container = Container(autoregister=True, auto_compile=False)

        class ServiceA:
            pass

        class ServiceB:
            def __init__(self, a: ServiceA) -> None:
                self.a = a

        # Only register ServiceB, let ServiceA be auto-registered during compilation
        container.register(ServiceB, lifetime=Lifetime.TRANSIENT)
        container.compile()

        # Both should be compiled
        assert ServiceKey.from_value(ServiceA) in container._compiled_providers
        assert ServiceKey.from_value(ServiceB) in container._compiled_providers

    def test_non_type_scoped_compilation_returns_none(self) -> None:
        """Non-type for scoped compilation returns None."""
        container = Container(auto_compile=False)

        # Register a string key with scope - should skip during scoped compilation
        string_key = ServiceKey(value="string_scoped_key", component=None)
        registration = Registration(
            service_key=string_key,
            lifetime=Lifetime.SCOPED,
            scope="request",
        )
        container._scoped_registry[(string_key, "request")] = registration

        container.compile()

        # String key should not have a compiled scoped provider
        assert (string_key, "request") not in container._scoped_compiled_providers

    def test_scoped_singleton_args_provider_creation_with_dependencies(self) -> None:
        """Scoped singleton with deps creates ScopedSingletonArgsProvider."""
        container = Container(auto_compile=False)

        class ServiceA:
            pass

        class ServiceB:
            def __init__(self, a: ServiceA) -> None:
                self.a = a

        container.register(ServiceA, lifetime=Lifetime.TRANSIENT)
        container.register(ServiceB, scope="request", lifetime=Lifetime.SCOPED)

        container.compile()

        service_key_b = ServiceKey.from_value(ServiceB)
        provider = container._scoped_compiled_providers.get((service_key_b, "request"))

        assert provider is not None
        assert isinstance(provider, ScopedSingletonArgsProvider)


class TestForwardReferenceHandling:
    """Tests for forward reference handling with NameError."""

    def test_forward_reference_name_error_in_resolve(self) -> None:
        """NameError for forward refs defaults to no scope in resolve."""
        container = Container()

        # Create a function with a forward reference that can't be resolved
        # This simulates PEP 563 behavior where annotations are strings
        def handler(service: "NonExistentService") -> None:  # type: ignore[name-defined] # noqa: F821
            pass

        # The resolve should catch the NameError and default to no scope
        result = container.resolve(handler)

        # Should return an Injected (not ScopedInjected) because scope detection failed
        assert isinstance(result, _InjectedFunction)

    @pytest.mark.asyncio
    async def test_aresolve_forward_reference_name_error(self) -> None:
        """aresolve catches NameError for forward refs gracefully."""
        container = Container()

        # Create a function with a forward reference that can't be resolved
        def handler(service: "AnotherNonExistentService") -> None:  # type: ignore[name-defined] # noqa: F821
            pass

        # The aresolve should catch the NameError and default to no scope
        result = await container.aresolve(handler)

        # Should return an Injected (not ScopedInjected)
        assert isinstance(result, _InjectedFunction)


class TestAsyncResolutionEdgeCases:
    """Tests for async resolution edge cases."""

    @pytest.mark.asyncio
    async def test_aresolve_type_singleton_cache_hit(self) -> None:
        """aresolve uses type singleton cache."""
        container = Container()

        class ServiceA:
            pass

        container.register(ServiceA, lifetime=Lifetime.SINGLETON)

        # First resolve to populate cache
        instance1 = container.resolve(ServiceA)

        # aresolve should use the cached singleton
        instance2 = await container.aresolve(ServiceA)

        assert instance1 is instance2

    @pytest.mark.asyncio
    async def test_aresolve_circular_dependency_detection(self) -> None:
        """aresolve detects circular dependencies."""
        container = Container()

        # Use module-level classes for circular dependency detection
        # These are defined at module level to avoid forward reference issues
        with pytest.raises(DIWireCircularDependencyError):
            await container.aresolve(_CircularServiceA)

    @pytest.mark.asyncio
    async def test_aresolve_scope_mismatch(self) -> None:
        """aresolve raises scope mismatch error."""
        container = Container(autoregister=False)

        class ServiceA:
            pass

        # Manually create registration with scope in global registry
        # This triggers scope mismatch when resolved in wrong scope
        service_key = ServiceKey.from_value(ServiceA)
        registration = Registration(
            service_key=service_key,
            lifetime=Lifetime.SCOPED,
            scope="request",
        )
        container._registry[service_key] = registration

        # Resolve within a different scope - should raise scope mismatch
        with container.enter_scope("wrong_scope"):
            with pytest.raises(DIWireScopeMismatchError):
                await container.aresolve(ServiceA)

    @pytest.mark.asyncio
    async def test_aresolve_instance_registration_with_scoped_cache(self) -> None:
        """aresolve caches scoped instances."""
        container = Container()

        class ServiceA:
            pass

        specific_instance = ServiceA()
        container.register(
            ServiceA,
            instance=specific_instance,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        async with container.enter_scope("request"):
            result = await container.aresolve(ServiceA)
            assert result is specific_instance

    @pytest.mark.asyncio
    async def test_aresolve_generator_factory_unsupported_lifetime(self) -> None:
        """Singleton generator factory raises error for unsupported lifetime."""
        from typing import Any

        class ServiceA:
            pass

        def generator_factory() -> Generator[ServiceA, Any, Any]:
            yield ServiceA()

        container = Container()
        container.register(
            ServiceA,
            factory=generator_factory,
            lifetime=Lifetime.SINGLETON,
            scope="request",
        )

        async with container.enter_scope("request"):
            with pytest.raises(DIWireGeneratorFactoryUnsupportedLifetimeError):
                await container.aresolve(ServiceA)

    @pytest.mark.asyncio
    async def test_aresolve_sync_generator_factory(self) -> None:
        """aresolve handles sync generator factories."""
        from typing import Any

        cleanup_called = []

        class ServiceA:
            pass

        def generator_factory() -> Generator[ServiceA, Any, Any]:
            try:
                yield ServiceA()
            finally:
                cleanup_called.append(True)

        container = Container()
        container.register(
            ServiceA,
            factory=generator_factory,
            lifetime=Lifetime.SCOPED,
            scope="request",
        )

        async with container.enter_scope("request"):
            result = await container.aresolve(ServiceA)
            assert isinstance(result, ServiceA)

        # Cleanup should be called
        assert cleanup_called == [True]

    @pytest.mark.asyncio
    async def test_aresolve_singleton_caching_in_factory_path(self) -> None:
        """aresolve caches singleton instances from factory."""
        call_count = 0

        class ServiceA:
            pass

        def factory() -> ServiceA:
            nonlocal call_count
            call_count += 1
            return ServiceA()

        container = Container()
        container.register(ServiceA, factory=factory, lifetime=Lifetime.SINGLETON)

        instance1 = await container.aresolve(ServiceA)
        instance2 = await container.aresolve(ServiceA)

        assert instance1 is instance2
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_aresolve_missing_dependencies_error(self) -> None:
        """aresolve raises missing dependencies error."""
        container = Container(autoregister=False)

        class ServiceA:
            pass

        class ServiceB:
            def __init__(self, a: ServiceA) -> None:
                self.a = a

        container.register(ServiceB)  # ServiceA not registered

        with pytest.raises(DIWireMissingDependenciesError):
            await container.aresolve(ServiceB)

    @pytest.mark.asyncio
    async def test_aget_resolved_dependencies_async_fallback(self) -> None:
        """Async dependency fallback paths in async resolution."""

        class ServiceA:
            pass

        async def async_factory() -> ServiceA:
            return ServiceA()

        class ServiceB:
            def __init__(self, a: ServiceA) -> None:
                self.a = a

        container = Container(auto_compile=False)
        container.register(ServiceA, factory=async_factory, lifetime=Lifetime.TRANSIENT)
        container.register(ServiceB, lifetime=Lifetime.TRANSIENT)

        # Without compilation, should fall back to registry check for async
        result = await container.aresolve(ServiceB)
        assert isinstance(result, ServiceB)
        assert isinstance(result.a, ServiceA)

    @pytest.mark.asyncio
    async def test_aget_resolved_dependencies_diwire_error_with_defaults(self) -> None:
        """DIWireError uses defaults in async resolution."""
        container = Container(autoregister=False)

        class UnregisteredService:
            pass

        default_service = UnregisteredService()

        class MyClass:
            def __init__(self, service: UnregisteredService = default_service) -> None:
                self.service = service

        container.register(MyClass)

        # Should use default value when resolution fails
        result = await container.aresolve(MyClass)
        assert result.service is default_service

    @pytest.mark.asyncio
    async def test_scope_exit_stack_cleanup(self) -> None:
        """aclear_scope cleans up exit stack."""
        cleanup_called = []

        class ServiceA:
            pass

        def generator_factory() -> Generator[ServiceA, None, None]:
            try:
                yield ServiceA()
            finally:
                cleanup_called.append(True)

        container = Container()
        container.register(
            ServiceA,
            factory=generator_factory,
            lifetime=Lifetime.SCOPED,
            scope="request",
        )

        # Use sync context manager but call aresolve
        with container.enter_scope("request"):
            result = container.resolve(ServiceA)
            assert isinstance(result, ServiceA)

        # Cleanup should be called via sync exit stack
        assert cleanup_called == [True]

    def test_return_scoped_registration(self) -> None:
        """_get_registration returns scoped registration."""
        container = Container()

        class ServiceA:
            pass

        specific_instance = ServiceA()
        container.register(
            ServiceA,
            instance=specific_instance,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        # Create a scope context
        scope_id = _ScopeId(segments=(("request", 1),))
        token = _current_scope.set(scope_id)
        try:
            service_key = ServiceKey.from_value(ServiceA)
            registration = container._get_registration(service_key, scope_id)

            assert registration.scope == "request"
            assert registration.instance is specific_instance
        finally:
            _current_scope.reset(token)

    @pytest.mark.asyncio
    async def test_nested_scope_diwire_error_continues(self) -> None:
        """DIWireError during nested scope detection is caught gracefully."""
        container = Container(autoregister=False)

        class ServiceA:
            pass

        class ServiceB:
            def __init__(self, a: ServiceA) -> None:
                self.a = a

        # Register ServiceB with scope but don't register ServiceA
        container.register(ServiceB, scope="request", lifetime=Lifetime.SCOPED)

        # _find_scope_in_dependencies should handle the DIWireError gracefully
        # when checking nested deps of unregistered ServiceA
        # This tests that the method doesn't crash on DIWireError

        # This is an indirect test - we create a function that depends on ServiceB
        def handler(b: Annotated[ServiceB, Injected()]) -> ServiceB:
            return b

        # resolve should work without crashing on nested scope detection
        injected = container.resolve(handler, scope="request")

        # Verify it's a ScopedInjected (scope was detected from ServiceB registration)
        assert isinstance(injected, _ScopedInjectedFunction)


class TestMissingCoverageSync:
    """Tests for sync resolution missing coverage."""

    def test_sync_generator_factory_singleton_raises(self) -> None:
        """Sync generator factory with SINGLETON lifetime raises error."""
        from typing import Any

        container = Container()

        class ServiceA:
            pass

        def generator_factory() -> Generator[ServiceA, Any, Any]:
            yield ServiceA()

        container.register(
            ServiceA,
            factory=generator_factory,
            lifetime=Lifetime.SINGLETON,
            scope="request",
        )

        with container.enter_scope("request"):
            with pytest.raises(DIWireGeneratorFactoryUnsupportedLifetimeError):
                container.resolve(ServiceA)

    def test_compiled_factory_handler_generator_singleton_raises(self) -> None:
        """Compiled factory handler rejects generator for SINGLETON lifetime."""

        class ServiceA:
            pass

        class ScopedMarker:
            pass

        container = Container()
        container.register(ScopedMarker, scope="request", lifetime=Lifetime.SCOPED)

        def generator_factory() -> Generator[ServiceA, None, None]:
            yield ServiceA()

        handler = container._make_compiled_factory_result_handler(
            ServiceKey.from_value(ServiceA),
            Lifetime.SINGLETON,
            None,
        )

        with container.enter_scope("request"):
            with pytest.raises(DIWireGeneratorFactoryUnsupportedLifetimeError):
                handler(generator_factory())

    def test_compiled_factory_handler_generator_no_yield_raises(self) -> None:
        """Compiled factory handler raises when generator yields nothing."""

        class ServiceA:
            pass

        class ScopedMarker:
            pass

        container = Container()
        container.register(ScopedMarker, scope="request", lifetime=Lifetime.SCOPED)

        def generator_factory() -> Generator[ServiceA, None, None]:
            return
            yield  # type: ignore[misc]  # unreachable but needed for generator

        handler = container._make_compiled_factory_result_handler(
            ServiceKey.from_value(ServiceA),
            Lifetime.TRANSIENT,
            None,
        )

        with container.enter_scope("request"):
            with pytest.raises(DIWireGeneratorFactoryDidNotYieldError):
                handler(generator_factory())

    def test_compiled_factory_handler_generator_yields_and_closes(self) -> None:
        """Compiled factory handler yields instance and registers cleanup."""

        class ServiceA:
            pass

        class ScopedMarker:
            pass

        cleanup: list[str] = []
        container = Container()
        container.register(ScopedMarker, scope="request", lifetime=Lifetime.SCOPED)

        def generator_factory() -> Generator[ServiceA, None, None]:
            try:
                yield ServiceA()
            finally:
                cleanup.append("closed")

        handler = container._make_compiled_factory_result_handler(
            ServiceKey.from_value(ServiceA),
            Lifetime.TRANSIENT,
            None,
        )

        with container.enter_scope("request"):
            instance = handler(generator_factory())
            assert isinstance(instance, ServiceA)
            assert cleanup == []

        assert cleanup == ["closed"]

    def test_resolve_instance_registration_stores_singleton(self) -> None:
        """Instance registration without scope stores in _singletons."""
        container = Container(autoregister=False, auto_compile=False)

        class ServiceA:
            pass

        instance = ServiceA()
        service_key = ServiceKey.from_value(ServiceA)

        # Directly add registration to registry (bypassing normal register path
        # which already caches in _singletons)
        container._registry[service_key] = Registration(
            service_key=service_key,
            instance=instance,
            lifetime=Lifetime.SINGLETON,
            scope=None,
        )

        resolved = container.resolve(ServiceA)
        assert resolved is instance
        assert service_key in container._singletons


class TestCoverageEdgeCases:
    """Tests for specific edge cases to improve coverage."""

    def test_compile_dependency_from_registry(self) -> None:
        """_compile_or_get_provider compiles dependency from registry."""
        container = Container(auto_compile=False, autoregister=False)

        class ServiceA:
            pass

        class ServiceB:
            def __init__(self, a: ServiceA) -> None:
                self.a = a

        # Register ServiceB first, then ServiceA
        # Dict iteration order is insertion order in Python 3.7+
        # So ServiceB will be compiled first, and ServiceA will be found in registry
        # but not yet in _compiled_providers
        container.register(ServiceB, lifetime=Lifetime.TRANSIENT)
        container.register(ServiceA, lifetime=Lifetime.TRANSIENT)

        container.compile()

        # Both should be compiled
        service_key_a = ServiceKey.from_value(ServiceA)
        service_key_b = ServiceKey.from_value(ServiceB)
        assert service_key_a in container._compiled_providers
        assert service_key_b in container._compiled_providers

    def test_compile_scoped_registration_without_scoped_registry(self) -> None:
        """_compile_scoped_registration handles empty scoped registry."""
        container = Container(auto_compile=False, autoregister=False)

        class ServiceA:
            pass

        class ServiceB:
            def __init__(self, a: ServiceA) -> None:
                self.a = a

        container.register(ServiceA, lifetime=Lifetime.TRANSIENT)

        service_key_b = ServiceKey.from_value(ServiceB)
        registration = Registration(
            service_key=service_key_b,
            lifetime=Lifetime.SCOPED,
            scope="request",
        )

        provider = container._compile_scoped_registration(service_key_b, registration, "request")

        assert isinstance(provider, ScopedSingletonArgsProvider)

    def test_compile_auto_registration_returns_none(self) -> None:
        """_compile_or_get_provider auto-registers but compilation fails."""
        container = Container(auto_compile=False, autoregister=True)

        class ServiceA:
            # str dependency without default - compilation will fail
            def __init__(self, name: str) -> None:
                self.name = name

        class ServiceB:
            def __init__(self, a: ServiceA) -> None:
                self.a = a

        # Only register ServiceB - ServiceA will be auto-registered
        container.register(ServiceB, lifetime=Lifetime.TRANSIENT)

        container.compile()

        # ServiceB compilation fails because ServiceA (auto-registered) can't be compiled
        # (str dependency without default)
        service_key_b = ServiceKey.from_value(ServiceB)
        assert service_key_b not in container._compiled_providers

        # ServiceA was auto-registered but not compiled (returns None from line 862)
        service_key_a = ServiceKey.from_value(ServiceA)
        assert service_key_a not in container._compiled_providers
        # But it should be in registry (auto-registered)
        assert service_key_a in container._registry

    def test_compile_scoped_registration_returns_none(self) -> None:
        """_compile_registration returns None for scoped registrations."""
        container = Container(auto_compile=False)

        class ServiceA:
            pass

        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)
        container.compile()

        # Scoped registrations are skipped in _compiled_providers
        service_key = ServiceKey.from_value(ServiceA)
        assert service_key not in container._compiled_providers

        # But they should be in _scoped_compiled_providers
        assert (service_key, "request") in container._scoped_compiled_providers

    def test_compile_scoped_registration_with_scoped_dependency(self) -> None:
        """Scoped registration compilation returns None when dependency can't be compiled."""
        container = Container(auto_compile=False, autoregister=False)

        class ServiceA:
            pass

        class ServiceB:
            def __init__(self, a: ServiceA) -> None:
                self.a = a

        # Only register ServiceB (scoped), but NOT ServiceA
        # When compiling ServiceB, _compile_or_get_provider(ServiceA) will return None
        # because ServiceA is not in _compiled_providers, not in _registry, and auto_register is disabled
        container.register(ServiceB, scope="request", lifetime=Lifetime.SCOPED)

        container.compile()

        # ServiceB should NOT have a scoped compiled provider because its dependency
        # (ServiceA) couldn't be compiled
        service_key_b = ServiceKey.from_value(ServiceB)
        assert (service_key_b, "request") not in container._scoped_compiled_providers

    def test_compile_scoped_registration_skips_scoped_dependency(self) -> None:
        """Scoped compilation skips when dependencies have scoped registrations."""
        container = Container(auto_compile=False, autoregister=False)

        class ServiceA:
            def __init__(self, name: str) -> None:
                self.name = name

        class ServiceB:
            def __init__(self, a: ServiceA) -> None:
                self.a = a

        global_instance = ServiceA(name="global")
        scoped_instance = ServiceA(name="scoped")

        container.register(ServiceA, instance=global_instance, lifetime=Lifetime.SINGLETON)
        container.register(
            ServiceA,
            instance=scoped_instance,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )
        container.register(ServiceB, scope="request", lifetime=Lifetime.SCOPED)

        container.compile()

        service_key_b = ServiceKey.from_value(ServiceB)
        assert (service_key_b, "request") not in container._scoped_compiled_providers

        with container.enter_scope("request"):
            resolved = container.resolve(ServiceB)
            assert resolved.a is scoped_instance

    def test_compiled_scoped_provider_uses_cache(self) -> None:
        """Compiled scoped provider caches instances correctly."""
        container = Container(auto_compile=False)

        class ServiceA:
            pass

        # Register scoped singleton
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)
        container.compile()

        # Verify compiled scoped provider exists
        service_key = ServiceKey.from_value(ServiceA)
        assert (service_key, "request") in container._scoped_compiled_providers

        # Enter the matching scope - compiled provider path will be used
        with container.enter_scope("request"):
            instance1 = container.resolve(ServiceA)
            instance2 = container.resolve(ServiceA)

            # Should be same instance (scoped singleton cached)
            assert instance1 is instance2

            # Verify it's in the scoped instances cache
            assert any(k[1] == service_key for k in container._scoped_instances)

    @pytest.mark.asyncio
    async def test_aresolve_type_singleton_fast_path_cache_hit(self) -> None:
        """aresolve uses _type_singletons cache."""
        container = Container()

        class ServiceA:
            pass

        instance = ServiceA()
        # Register with instance= which directly populates _type_singletons
        container.register(ServiceA, instance=instance)

        # aresolve should hit the fast path cache at line 1283-1285
        result = await container.aresolve(ServiceA)
        assert result is instance

    @pytest.mark.asyncio
    async def test_aresolve_circular_dependency_pure_async_path(self) -> None:
        """aresolve detects circular dependencies in async resolution path."""
        container = Container()

        # Use module-level classes to avoid forward reference issues
        # _AsyncCircularA depends on _AsyncCircularB and vice versa

        # Use async factories with Injected annotation to enable injection
        async def create_a(b: Annotated[_AsyncCircularB, Injected()]) -> _AsyncCircularA:
            return _AsyncCircularA(b)

        async def create_b(a: Annotated[_AsyncCircularA, Injected()]) -> _AsyncCircularB:
            return _AsyncCircularB(a)

        container.register(_AsyncCircularA, factory=create_a)
        container.register(_AsyncCircularB, factory=create_b)

        with pytest.raises(DIWireCircularDependencyError):
            await container.aresolve(_AsyncCircularA)

    @pytest.mark.asyncio
    async def test_aresolve_async_generator_singleton_inside_scope(self) -> None:
        """Async generator factory with SINGLETON lifetime raises inside scope."""
        container = Container()

        class ServiceA:
            pass

        async def async_gen_factory() -> AsyncGenerator[ServiceA, None]:
            yield ServiceA()

        container.register(
            ServiceA,
            factory=async_gen_factory,
            lifetime=Lifetime.SINGLETON,
            scope="request",
        )

        async with container.enter_scope("request"):
            # Inside scope, cache_scope is not None, so we hit line 1407
            with pytest.raises(DIWireGeneratorFactoryUnsupportedLifetimeError):
                await container.aresolve(ServiceA)

    @pytest.mark.asyncio
    async def test_aresolve_ignored_type_with_default(self) -> None:
        """aresolve skips ignored type with default in async resolution."""

        class ServiceWithIgnoredDefault:
            def __init__(self, name: str = "default") -> None:
                self.name = name

        container = Container(autoregister=True)
        result = await container.aresolve(ServiceWithIgnoredDefault)
        assert result.name == "default"

    @pytest.mark.asyncio
    async def test_aresolve_ignored_type_explicitly_registered(self) -> None:
        """aresolve uses registered ignored type (branch 1473->1479)."""

        class ServiceWithStr:
            def __init__(self, name: str) -> None:
                self.name = name

        container = Container(autoregister=True)
        # Explicitly register str - this is normally an ignored type
        container.register(str, instance="explicit_value")
        container.register(ServiceWithStr)

        # When resolving, str is in ignores AND in registry,
        # so we fall through to the normal resolution path at line 1479
        result = await container.aresolve(ServiceWithStr)
        assert result.name == "explicit_value"

    def test_get_scoped_registration_with_anonymous_scopes(self) -> None:
        """_get_scoped_registration iterates past anonymous scope segments."""
        container = Container()

        class Session:
            pass

        # Register a scoped singleton at "request" scope
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        # Create a scope ID with an anonymous segment (name=None)
        # This simulates entering nested scopes where inner one is anonymous
        scope_id = _ScopeId(segments=(("request", 1), (None, 2)))
        token = _current_scope.set(scope_id)
        try:
            service_key = ServiceKey.from_value(Session)
            # This should iterate past the anonymous segment and find "request"
            registration = container._get_scoped_registration(service_key, scope_id)
            assert registration is not None
            assert registration.scope == "request"
        finally:
            _current_scope.reset(token)

    def test_find_scope_in_dependencies_with_extraction_error(self) -> None:
        """_find_scope_in_dependencies catches DIWireError gracefully."""
        container = Container(autoregister=False)

        class ServiceA:
            pass

        class ServiceB:
            def __init__(self, a: ServiceA) -> None:
                self.a = a

        # Register ServiceB with scope but don't register ServiceA
        container.register(ServiceB, scope="request", lifetime=Lifetime.SCOPED)

        # Create a function that depends on ServiceB
        def handler(b: Annotated[ServiceB, Injected()]) -> ServiceB:
            return b

        # resolve should work without crashing - DIWireError during nested dep extraction is caught
        injected = container.resolve(handler, scope="request")

        # Should be ScopedInjected because scope was explicitly provided
        assert isinstance(injected, _ScopedInjectedFunction)

    def test_resolve_dependencies_error_with_default(self) -> None:
        """_resolve_dependencies handles error when param has default."""
        container = Container(autoregister=False)

        class UnregisteredService:
            pass

        default_instance = UnregisteredService()

        class ServiceWithDefault:
            def __init__(self, dep: UnregisteredService = default_instance) -> None:
                self.dep = dep

        container.register(ServiceWithDefault)

        # The UnregisteredService will fail to resolve, but has a default
        # So the resolution should succeed with default value
        result = container.resolve(ServiceWithDefault)
        assert result.dep is default_instance


class TestDependencyExtractionErrorHandling:
    """Tests for DIWireDependencyExtractionError handling in container."""

    def test_compile_handles_extraction_error_in_compute_async_deps(self) -> None:
        """compile() catches DIWireDependencyExtractionError in async deps computation."""

        # Create a class with a forward reference that cannot be resolved
        # This will cause get_type_hints to fail with NameError
        class BadAnnotation:
            def __init__(self, dep: "NonExistentType") -> None:  # type: ignore[name-defined] # noqa: F821
                pass

        container = Container(auto_compile=False)
        container.register(BadAnnotation)

        # compile() should not raise - it catches the DIWireDependencyExtractionError
        # and continues
        container.compile()
        assert container._is_compiled is True

    def test_scoped_injected_handles_extraction_error_in_find_scope(self) -> None:
        """ScopedInjected catches DIWireDependencyExtractionError in scope detection."""

        # Create a class with unresolvable forward reference in its dependencies
        class ServiceWithBadNestedDep:
            def __init__(self, dep: "UndefinedType") -> None:  # type: ignore[name-defined] # noqa: F821
                pass

        container = Container(autoregister=True)
        container.register(ServiceWithBadNestedDep)

        # Create a handler that depends on the service with bad nested deps
        def handler(service: Annotated[ServiceWithBadNestedDep, Injected()]) -> None:
            pass

        # resolve() should not raise during scope detection
        # It catches the DIWireDependencyExtractionError and continues
        result = container.resolve(handler)

        # Should return Injected (no scope detected due to extraction error)
        assert isinstance(result, _InjectedFunction)
