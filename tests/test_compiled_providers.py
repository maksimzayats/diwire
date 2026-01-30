"""Tests for compiled providers."""

import asyncio
import inspect
from collections.abc import AsyncGenerator, Coroutine, Generator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from diwire.compiled_providers import (
    FactoryProvider,
    InstanceProvider,
    ScopedSingletonArgsProvider,
    ScopedSingletonProvider,
    SingletonFactoryProvider,
)
from diwire.container import Container
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireGeneratorFactoryWithoutScopeError,
    DIWireScopeMismatchError,
)
from diwire.registry import Registration
from diwire.service_key import ServiceKey
from diwire.types import Lifetime


@dataclass
class ServiceA:
    """Simple service for testing."""

    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class ServiceB:
    """Service with dependency on ServiceA."""

    service_a: ServiceA
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class ServiceC:
    """Service with multiple dependencies."""

    service_a: ServiceA
    service_b: ServiceB
    id: str = field(default_factory=lambda: str(uuid4()))


class TestSingletonArgsTypeProvider:
    """Tests for SingletonArgsTypeProvider - singleton types with dependencies."""

    def test_singleton_with_dependency_returns_same_instance(self) -> None:
        """Singleton with dependencies should return the same instance."""
        container = Container()
        container.register(ServiceA, lifetime=Lifetime.SINGLETON)
        container.register(ServiceB, lifetime=Lifetime.SINGLETON)
        container.compile()

        instance1 = container.resolve(ServiceB)
        instance2 = container.resolve(ServiceB)

        assert instance1 is instance2
        assert isinstance(instance1.service_a, ServiceA)

    def test_singleton_dependency_is_shared(self) -> None:
        """Dependency of singleton should also be a singleton."""
        container = Container()
        container.register(ServiceA, lifetime=Lifetime.SINGLETON)
        container.register(ServiceB, lifetime=Lifetime.SINGLETON)
        container.compile()

        service_a = container.resolve(ServiceA)
        service_b = container.resolve(ServiceB)

        assert service_b.service_a is service_a

    def test_singleton_chain_of_dependencies(self) -> None:
        """Chain of singleton dependencies should share instances."""
        container = Container()
        container.register(ServiceA, lifetime=Lifetime.SINGLETON)
        container.register(ServiceB, lifetime=Lifetime.SINGLETON)
        container.register(ServiceC, lifetime=Lifetime.SINGLETON)
        container.compile()

        service_c = container.resolve(ServiceC)
        service_a_direct = container.resolve(ServiceA)
        service_b_direct = container.resolve(ServiceB)

        assert service_c.service_a is service_a_direct
        assert service_c.service_b is service_b_direct
        assert service_c.service_b.service_a is service_a_direct


class TestScopedSingletonProvider:
    """Tests for ScopedSingletonProvider - scoped singletons without deps."""

    def test_scoped_singleton_same_instance_in_scope(self) -> None:
        """Scoped singleton should return same instance within scope."""
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)
        container.compile()

        with container.enter_scope("request"):
            instance1 = container.resolve(ServiceA)
            instance2 = container.resolve(ServiceA)

        assert instance1 is instance2

    def test_scoped_singleton_different_instances_different_scopes(self) -> None:
        """Scoped singleton should return different instances in different scopes."""
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)
        container.compile()

        with container.enter_scope("request"):
            instance1 = container.resolve(ServiceA)

        with container.enter_scope("request"):
            instance2 = container.resolve(ServiceA)

        assert instance1 is not instance2
        assert instance1.id != instance2.id

    def test_scoped_singleton_outside_scope_creates_transient(self) -> None:
        """Scoped singleton resolved outside scope acts like transient."""
        # Note: The current implementation creates instances even outside scope
        # using the ScopedSingletonProvider.__call__ fallback
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)
        container.compile()

        # This tests the fallback path when scoped_cache is None
        # We need to test via internal provider mechanism
        service_key = ServiceKey.from_value(ServiceA)
        provider = container._scoped_compiled_providers.get((service_key, "request"))
        assert provider is not None

        # Call with scoped_cache=None - should create transient-like instance
        singletons: dict[ServiceKey, object] = {}
        instance1 = provider(singletons, None)
        instance2 = provider(singletons, None)

        # Without scope cache, each call creates new instance
        assert instance1 is not instance2


class TestScopedSingletonArgsProvider:
    """Tests for ScopedSingletonArgsProvider - scoped singletons with deps."""

    def test_scoped_singleton_with_dependency_same_scope(self) -> None:
        """Scoped singleton with dependencies returns same instance in scope."""
        container = Container()
        container.register(ServiceB, scope="request", lifetime=Lifetime.SCOPED)
        container.compile()

        with container.enter_scope("request"):
            # Resolve ServiceB multiple times - should be same instance
            service_b1 = container.resolve(ServiceB)
            service_b2 = container.resolve(ServiceB)

            # Same scoped singleton instance
            assert service_b1 is service_b2
            # Dependency is also the same
            assert service_b1.service_a is service_b2.service_a

    def test_scoped_singleton_with_deps_different_scopes(self) -> None:
        """Scoped singleton with deps gets different instances per scope."""
        container = Container()
        container.register(ServiceB, scope="request", lifetime=Lifetime.SCOPED)
        container.compile()

        with container.enter_scope("request"):
            service_b1 = container.resolve(ServiceB)

        with container.enter_scope("request"):
            service_b2 = container.resolve(ServiceB)

        assert service_b1 is not service_b2
        assert service_b1.service_a is not service_b2.service_a

    def test_scoped_singleton_args_outside_scope(self) -> None:
        """Test scoped singleton args provider fallback when outside scope."""
        container = Container()
        container.register(ServiceA, lifetime=Lifetime.TRANSIENT)
        container.register(ServiceB, scope="request", lifetime=Lifetime.SCOPED)
        container.compile()

        service_key_b = ServiceKey.from_value(ServiceB)
        provider = container._scoped_compiled_providers.get((service_key_b, "request"))
        assert provider is not None

        # Call with scoped_cache=None - tests the else branch
        singletons: dict[ServiceKey, object] = {}
        instance1 = provider(singletons, None)
        instance2 = provider(singletons, None)

        # Without scope cache, each call creates new instance
        assert instance1 is not instance2


class TestSingletonFactoryProvider:
    """Tests for SingletonFactoryProvider - factory-created singletons."""

    def test_singleton_factory_returns_same_instance(self) -> None:
        """Singleton created by factory should return same instance."""

        class ServiceAFactory:
            def __call__(self) -> ServiceA:
                return ServiceA(id="factory-created")

        container = Container()
        container.register(ServiceA, factory=ServiceAFactory, lifetime=Lifetime.SINGLETON)
        container.compile()

        instance1 = container.resolve(ServiceA)
        instance2 = container.resolve(ServiceA)

        assert instance1 is instance2
        assert instance1.id == "factory-created"

    def test_singleton_factory_called_once(self) -> None:
        """Singleton factory should only be called once."""
        call_count = 0

        class CountingFactory:
            def __call__(self) -> ServiceA:
                nonlocal call_count
                call_count += 1
                return ServiceA(id=f"call-{call_count}")

        container = Container()
        container.register(ServiceA, factory=CountingFactory, lifetime=Lifetime.SINGLETON)
        container.compile()

        for _ in range(5):
            container.resolve(ServiceA)

        assert call_count == 1

    def test_singleton_factory_with_dependency(self) -> None:
        """Singleton factory that resolves dependencies."""

        class ServiceBFactory:
            def __init__(self, container: Container) -> None:
                self._container = container

            def __call__(self) -> ServiceB:
                service_a = self._container.resolve(ServiceA)
                return ServiceB(service_a=service_a, id="factory-b")

        container = Container()
        container.register(ServiceA, lifetime=Lifetime.SINGLETON)
        container.register(ServiceB, factory=ServiceBFactory, lifetime=Lifetime.SINGLETON)
        container.compile()

        service_b1 = container.resolve(ServiceB)
        service_b2 = container.resolve(ServiceB)
        service_a = container.resolve(ServiceA)

        assert service_b1 is service_b2
        assert service_b1.service_a is service_a


class TestFactoryProvider:
    """Tests for FactoryProvider - factory-created instances."""

    def test_factory_provider_without_handler_returns_result(self) -> None:
        """FactoryProvider without a result handler returns the raw result."""

        class ServiceAFactory:
            def __call__(self) -> ServiceA:
                return ServiceA(id="factory")

        factory_provider = InstanceProvider(ServiceAFactory())
        provider = FactoryProvider(factory_provider)

        result = provider({}, None)

        assert isinstance(result, ServiceA)
        assert result.id == "factory"


class TestCompiledFactoryGeneratorHandling:
    """Tests for generator factories when using compiled providers."""

    def test_compiled_factory_generator_without_scope_raises(self) -> None:
        """Compiled factory returning a generator without scope raises."""

        class GeneratorFactory:
            def __call__(self) -> Generator[ServiceA, None, None]:
                yield ServiceA(id="generated")

        container = Container()
        container.register(ServiceA, factory=GeneratorFactory, lifetime=Lifetime.TRANSIENT)
        container.compile()

        service_key = ServiceKey.from_value(ServiceA)
        assert service_key in container._compiled_providers

        with pytest.raises(DIWireGeneratorFactoryWithoutScopeError):
            container.resolve(ServiceA)

    def test_compiled_singleton_factory_generator_without_scope_does_not_cache(self) -> None:
        """Singleton compiled factory returning a generator without scope is not cached."""

        class GeneratorFactory:
            def __call__(self) -> Generator[ServiceA, None, None]:
                yield ServiceA(id="generated")

        container = Container()
        container.register(ServiceA, factory=GeneratorFactory, lifetime=Lifetime.SINGLETON)
        container.compile()

        service_key = ServiceKey.from_value(ServiceA)
        provider = container._compiled_providers.get(service_key)
        assert isinstance(provider, SingletonFactoryProvider)

        with pytest.raises(DIWireGeneratorFactoryWithoutScopeError):
            container.resolve(ServiceA)

        assert service_key not in container._singletons
        assert provider._instance is None

    def test_compiled_async_generator_factory_sync_resolve_raises(self) -> None:
        """Async generator factories stay on the uncompiled sync path."""

        class AsyncGeneratorFactory:
            async def __call__(self) -> AsyncGenerator[ServiceA, None]:
                yield ServiceA(id="async")

        container = Container()
        container.register(ServiceA, factory=AsyncGeneratorFactory, lifetime=Lifetime.TRANSIENT)
        container.compile()

        service_key = ServiceKey.from_value(ServiceA)
        assert service_key not in container._compiled_providers

        with pytest.raises(DIWireAsyncDependencyInSyncContextError):
            container.resolve(ServiceA)

    def test_compiled_factory_returning_coroutine_raises(self) -> None:
        """Sync factory returning a coroutine raises and closes the coroutine."""
        coro_ref: Coroutine[Any, Any, ServiceA] | None = None

        class CoroutineFactory:
            def __call__(self) -> Coroutine[Any, Any, ServiceA]:
                nonlocal coro_ref

                async def build() -> ServiceA:
                    return ServiceA(id="async")

                coro_ref = build()
                return coro_ref

        container = Container()
        container.register(ServiceA, factory=CoroutineFactory, lifetime=Lifetime.TRANSIENT)
        container.compile()

        with pytest.raises(DIWireAsyncDependencyInSyncContextError):
            container.resolve(ServiceA)

        assert coro_ref is not None
        assert inspect.getcoroutinestate(coro_ref) == inspect.CORO_CLOSED

    def test_compiled_factory_returning_async_generator_raises(self) -> None:
        """Sync factory returning an async generator raises and can be closed."""
        async_gen_ref: AsyncGenerator[ServiceA, None] | None = None

        class AsyncGeneratorWrapperFactory:
            def __call__(self) -> AsyncGenerator[ServiceA, None]:
                nonlocal async_gen_ref

                async def build() -> AsyncGenerator[ServiceA, None]:
                    yield ServiceA(id="async")

                async_gen_ref = build()
                return async_gen_ref

        container = Container()
        container.register(
            ServiceA,
            factory=AsyncGeneratorWrapperFactory,
            lifetime=Lifetime.TRANSIENT,
        )
        container.compile()

        with pytest.raises(DIWireAsyncDependencyInSyncContextError):
            container.resolve(ServiceA)

        assert async_gen_ref is not None
        asyncio.run(async_gen_ref.aclose())


class TestCompiledProvidersCacheHit:
    """Tests for compiled providers cache hit paths."""

    def test_scoped_singleton_provider_cache_hit(self) -> None:
        """Test ScopedSingletonProvider returns cached instance on second call with scoped_cache."""
        service_key = ServiceKey.from_value(ServiceA)
        provider = ScopedSingletonProvider(ServiceA, service_key)

        singletons: dict[ServiceKey, object] = {}
        scoped_cache: dict[ServiceKey, object] = {}

        # First call - creates and caches instance
        instance1 = provider(singletons, scoped_cache)
        assert isinstance(instance1, ServiceA)
        assert service_key in scoped_cache

        # Second call - should return cached instance
        instance2 = provider(singletons, scoped_cache)
        assert instance2 is instance1

    def test_scoped_singleton_args_provider_cache_hit(self) -> None:
        """Test ScopedSingletonArgsProvider returns cached instance on second call with scoped_cache."""
        service_key_b = ServiceKey.from_value(ServiceB)
        service_key_a = ServiceKey.from_value(ServiceA)

        # Create provider for ServiceA (dependency)
        dep_instance = ServiceA()
        dep_provider = InstanceProvider(dep_instance)

        # Create scoped singleton args provider for ServiceB
        provider = ScopedSingletonArgsProvider(
            ServiceB,
            service_key_b,
            ("service_a",),
            (dep_provider,),
        )

        singletons: dict[ServiceKey, object] = {}
        scoped_cache: dict[ServiceKey, object] = {}

        # First call - creates and caches instance
        instance1 = provider(singletons, scoped_cache)
        assert isinstance(instance1, ServiceB)
        assert service_key_b in scoped_cache

        # Second call - should return cached instance
        instance2 = provider(singletons, scoped_cache)
        assert instance2 is instance1
        assert instance2.service_a is dep_instance

    def test_singleton_factory_provider_cache_hit(self) -> None:
        """Test SingletonFactoryProvider returns cached instance without calling factory again."""
        call_count = 0

        class CountingFactory:
            def __call__(self) -> ServiceA:
                nonlocal call_count
                call_count += 1
                return ServiceA(id=f"call-{call_count}")

        service_key = ServiceKey.from_value(ServiceA)
        factory_instance = CountingFactory()
        factory_provider = InstanceProvider(factory_instance)

        provider = SingletonFactoryProvider(service_key, factory_provider)

        singletons: dict[ServiceKey, object] = {}

        # First call - creates instance
        instance1 = provider(singletons, None)
        assert call_count == 1
        assert isinstance(instance1, ServiceA)

        # Second call - should return cached instance without calling factory
        instance2 = provider(singletons, None)
        assert instance2 is instance1
        assert call_count == 1  # Factory not called again


class TestCompiledProviderIntegration:
    """Integration tests for compiled providers."""

    def test_mixed_lifetimes_compiled(self) -> None:
        """Mix of singleton, transient, and scoped all compiled."""
        container = Container()
        container.register(ServiceA, lifetime=Lifetime.SINGLETON)
        container.register(ServiceB, lifetime=Lifetime.TRANSIENT)
        container.register(ServiceC, scope="request", lifetime=Lifetime.SCOPED)
        container.compile()

        # Singleton behavior
        singleton_a1 = container.resolve(ServiceA)
        singleton_a2 = container.resolve(ServiceA)
        assert singleton_a1 is singleton_a2

        # Transient behavior
        transient_b1 = container.resolve(ServiceB)
        transient_b2 = container.resolve(ServiceB)
        assert transient_b1 is not transient_b2
        # But transient uses singleton dependency
        assert transient_b1.service_a is transient_b2.service_a

        # Scoped behavior
        with container.enter_scope("request"):
            scoped_c1 = container.resolve(ServiceC)
            scoped_c2 = container.resolve(ServiceC)
            assert scoped_c1 is scoped_c2

    def test_compiled_container_fast_path(self) -> None:
        """Compiled container uses fast type lookup."""
        container = Container()
        container.register(ServiceA, lifetime=Lifetime.SINGLETON)
        container.compile()

        # First resolution populates type cache
        instance1 = container.resolve(ServiceA)

        # Type should be in type singletons cache
        assert ServiceA in container._type_singletons

        # Second resolution uses fast path
        instance2 = container.resolve(ServiceA)
        assert instance1 is instance2


class TestCompilationMissingCoverage:
    """Tests for compilation missing coverage."""

    def test_compile_or_get_provider_registration_found(self) -> None:
        """Registration found in registry and compiled."""
        container = Container(autoregister=False, auto_compile=False)

        class ServiceALocal:
            pass

        class ServiceBLocal:
            def __init__(self, a: ServiceALocal) -> None:
                self.a = a

        # Register both services BEFORE compilation
        container.register(ServiceALocal, lifetime=Lifetime.TRANSIENT)
        container.register(ServiceBLocal, lifetime=Lifetime.TRANSIENT)

        # Compile - when compiling ServiceB, it finds ServiceA in registry
        container.compile()

        assert ServiceKey.from_value(ServiceALocal) in container._compiled_providers
        assert ServiceKey.from_value(ServiceBLocal) in container._compiled_providers

    def test_scoped_compilation_ignored_type_without_default(self) -> None:
        """Scoped registration with ignored type (str) without default returns None."""
        container = Container(autoregister=False, auto_compile=False)

        class ServiceWithStr:
            def __init__(self, name: str) -> None:
                self.name = name

        container.register(
            ServiceWithStr,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )
        container.compile()

        service_key = ServiceKey.from_value(ServiceWithStr)
        # Should NOT have a compiled scoped provider
        assert (service_key, "request") not in container._scoped_compiled_providers

    def test_scoped_compilation_dependency_fails(self) -> None:
        """Scoped registration where dependency compilation fails."""
        container = Container(autoregister=False, auto_compile=False)

        class UnregisteredDep:
            pass

        class ServiceBLocal:
            def __init__(self, dep: UnregisteredDep) -> None:
                self.dep = dep

        # Add UnregisteredDep to ignores so it can't be auto-registered
        container._autoregister_ignores.add(UnregisteredDep)
        container.register(
            ServiceBLocal,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )
        container.compile()

        service_key = ServiceKey.from_value(ServiceBLocal)
        assert (service_key, "request") not in container._scoped_compiled_providers

    def test_async_deps_cache_non_class_key(self) -> None:
        """Non-class service key causes DIWireError during dependency extraction."""
        container = Container(autoregister=False, auto_compile=False)

        # Register a string service key - dependency extraction will fail
        string_key = ServiceKey(value="string_service", component=None)
        container._registry[string_key] = Registration(
            service_key=string_key,
            lifetime=Lifetime.TRANSIENT,
        )

        # compile() should not crash - DIWireError is caught
        container.compile()
        assert container._is_compiled is True

    def test_compiled_scoped_resolution_scope_mismatch_fallthrough(self) -> None:
        """Test branch 1107->1120: compiled scoped resolution falls through when scope doesn't match."""

        @dataclass
        class ScopedService:
            pass

        container = Container()
        service_key = ServiceKey.from_value(ScopedService)

        # Register the service for scope "scope_a"
        container.register(ScopedService, lifetime=Lifetime.SCOPED, scope="scope_a")
        container.compile()  # Creates compiled scoped provider for (service_key, "scope_a")

        # Manually create a scoped registration that will be found by _get_scoped_registration
        # but with a scope name that doesn't match the current scope's segments
        # This simulates an edge case where the registration scope differs from cache key lookup
        scoped_reg = Registration(
            service_key=service_key,
            lifetime=Lifetime.SCOPED,
            scope="scope_a",
        )
        # Put it in the scoped registry under "scope_b" so it's found when in scope_b
        container._scoped_registry[(service_key, "scope_b")] = scoped_reg

        # Enter scope_b - _get_scoped_registration will find the registration for "scope_b"
        # but scoped_registration.scope is "scope_a"
        # So cache_scope = current_scope.get_cache_key_for_scope("scope_a") returns None
        # because scope_b doesn't contain scope_a
        with container.enter_scope("scope_b"):
            # The scoped_provider exists for (service_key, "scope_a") from compilation
            # But cache_scope is None -> falls through branch 1107->1120
            # Then normal resolution finds the registration and raises scope mismatch
            with pytest.raises(DIWireScopeMismatchError):
                container.resolve(ScopedService)

    def test_compiled_scoped_transient_not_cached(self) -> None:
        """Compiled scoped providers skip caching for TRANSIENT lifetime."""
        container = Container()

        class ServiceLocal:
            pass

        container.register(ServiceLocal, scope="request", lifetime=Lifetime.TRANSIENT)
        container.compile()

        with container.enter_scope("request"):
            # Each resolution should return a new instance (not cached)
            instance1 = container.resolve(ServiceLocal)
            instance2 = container.resolve(ServiceLocal)
            assert instance1 is not instance2

    def test_compile_scoped_provider_returns_none_on_dependency_extraction_error(self) -> None:
        """_compile_scoped_provider returns None when dependency extraction fails."""
        container = Container(autoregister=False, auto_compile=False)

        class ServiceWithBadDep:
            def __init__(
                self,
                dep: "UndefinedType",  # type: ignore[name-defined]  # noqa: F821
            ) -> None:
                self.dep = dep

        container.register(
            ServiceWithBadDep,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        # Compilation should not raise - it returns None for this registration
        container.compile()

        # The service should not be in compiled scoped providers
        service_key = ServiceKey.from_value(ServiceWithBadDep)
        assert (service_key, "request") not in container._scoped_compiled_providers

    def test_factory_class_with_uncompilable_dependency_returns_none(self) -> None:
        """Factory class with uncompilable dependency returns None from compilation.

        This test covers line 902 in container.py where a factory class has
        a dependency that cannot be compiled, causing _compile_registration
        to return None.
        """

        class UncompilableDep:
            """Dependency that cannot be compiled."""

            def __init__(
                self,
                broken: "UndefinedType",  # type: ignore[name-defined]  # noqa: F821
            ) -> None:
                self.broken = broken

        class FactoryClass:
            """Factory that depends on an uncompilable type."""

            def __init__(self, dep: UncompilableDep) -> None:
                self.dep = dep

            def __call__(self) -> ServiceA:
                return ServiceA(id="factory-result")

        container = Container(autoregister=False, auto_compile=False)

        # Register the factory class which depends on UncompilableDep
        container.register(ServiceA, factory=FactoryClass, lifetime=Lifetime.TRANSIENT)
        # Register UncompilableDep so it exists in registry but has bad deps
        container.register(UncompilableDep, lifetime=Lifetime.TRANSIENT)

        # Compile - should not raise, factory registration should be skipped
        container.compile()

        # ServiceA should NOT be compiled since its factory can't be compiled
        service_key = ServiceKey.from_value(ServiceA)
        assert service_key not in container._compiled_providers

    def test_compile_or_get_provider_handles_auto_registration_error(self) -> None:
        """Auto-registration errors during compilation return None gracefully.

        This test covers lines 1043-1044 in container.py where an error during
        auto-registration causes _compile_or_get_provider to return None.

        We trigger this by having a service that depends on a type annotated
        with Component. The type passes the ignores filter (line 941), but when
        _compile_or_get_provider tries to auto-register it, it raises
        DIWireComponentSpecifiedError because components require explicit registration.
        """
        from typing import Annotated

        from diwire.service_key import Component

        class DatabaseConn:
            """A type that will be used with a component annotation."""

        class ServiceWithComponentDep:
            """Service with a dependency on a component-annotated type."""

            def __init__(
                self,
                db: Annotated[DatabaseConn, Component("primary")],
            ) -> None:
                self.db = db

        container = Container(autoregister=True, auto_compile=False)

        # Register the top-level service
        container.register(ServiceWithComponentDep, lifetime=Lifetime.TRANSIENT)

        # Don't register DatabaseConn with component "primary" -
        # when compiling, _compile_or_get_provider will try to auto-register
        # the component-annotated dependency, which raises DIWireComponentSpecifiedError
        # because auto-registration doesn't support components (line 2039-2040)
        container.compile()

        # ServiceWithComponentDep should NOT be compiled due to dependency error
        service_key = ServiceKey.from_value(ServiceWithComponentDep)
        assert service_key not in container._compiled_providers
