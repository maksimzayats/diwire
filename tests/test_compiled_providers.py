"""Tests for compiled providers."""

from dataclasses import dataclass, field
from uuid import uuid4

from diwire.container import Container
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
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.compile()

        with container.start_scope("request"):
            instance1 = container.resolve(ServiceA)
            instance2 = container.resolve(ServiceA)

        assert instance1 is instance2

    def test_scoped_singleton_different_instances_different_scopes(self) -> None:
        """Scoped singleton should return different instances in different scopes."""
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.compile()

        with container.start_scope("request"):
            instance1 = container.resolve(ServiceA)

        with container.start_scope("request"):
            instance2 = container.resolve(ServiceA)

        assert instance1 is not instance2
        assert instance1.id != instance2.id

    def test_scoped_singleton_outside_scope_creates_transient(self) -> None:
        """Scoped singleton resolved outside scope acts like transient."""
        # Note: The current implementation creates instances even outside scope
        # using the ScopedSingletonProvider.__call__ fallback
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.compile()

        # This tests the fallback path when scoped_cache is None
        # We need to test via internal provider mechanism
        from diwire.service_key import ServiceKey

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
        container.register(ServiceB, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.compile()

        with container.start_scope("request"):
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
        container.register(ServiceB, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.compile()

        with container.start_scope("request"):
            service_b1 = container.resolve(ServiceB)

        with container.start_scope("request"):
            service_b2 = container.resolve(ServiceB)

        assert service_b1 is not service_b2
        assert service_b1.service_a is not service_b2.service_a

    def test_scoped_singleton_args_outside_scope(self) -> None:
        """Test scoped singleton args provider fallback when outside scope."""
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(ServiceB, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.compile()

        from diwire.service_key import ServiceKey

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


class TestCompiledProviderIntegration:
    """Integration tests for compiled providers."""

    def test_mixed_lifetimes_compiled(self) -> None:
        """Mix of singleton, transient, and scoped all compiled."""
        container = Container()
        container.register(ServiceA, lifetime=Lifetime.SINGLETON)
        container.register(ServiceB, lifetime=Lifetime.TRANSIENT)
        container.register(ServiceC, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
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
        with container.start_scope("request"):
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
