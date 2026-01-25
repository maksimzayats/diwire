"""Comprehensive tests for async functionality in diwire.

Tests for aresolve(), async factories, async generators, AsyncInjected, and AsyncScopedInjected.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass, field
from inspect import signature
from typing import Annotated

import pytest

from diwire.container import (
    AsyncInjected,
    AsyncScopedInjected,
    Container,
    Injected,
    ScopedInjected,
    _current_scope,
)
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireAsyncGeneratorFactoryDidNotYieldError,
    DIWireAsyncGeneratorFactoryWithoutScopeError,
    DIWireCircularDependencyError,
)
from diwire.types import FromDI, Lifetime

# =============================================================================
# Test Data Classes
# =============================================================================


@dataclass
class Session:
    """A session with a unique ID for testing."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Service:
    """A service that depends on Session."""

    session: Session


@dataclass
class ServiceA:
    """Service A for testing."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class ServiceB:
    """Service B that depends on ServiceA."""

    service_a: ServiceA


@dataclass
class SyncServiceForMixed:
    """Sync service for mixed sync/async tests."""

    value: str = "sync"


@dataclass
class MixedService:
    """Service with mixed sync and async dependencies."""

    sync: SyncServiceForMixed
    async_dep: ServiceA


@dataclass
class ServiceXForScope:
    """Service X depending on Session for scoped tests."""

    session: Session


@dataclass
class ServiceYForScope:
    """Service Y depending on Session for scoped tests."""

    session: Session


# Module-level circular classes for async tests
class CircularForAsync_A:
    """Circular A for async tests."""

    def __init__(self, b: CircularForAsync_B) -> None:
        self.b = b


class CircularForAsync_B:
    """Circular B for async tests."""

    def __init__(self, a: CircularForAsync_A) -> None:
        self.a = a


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture()
def container() -> Container:
    """Default container with auto-registration enabled."""
    return Container(register_if_missing=True)


@pytest.fixture()
def container_singleton() -> Container:
    """Container with lifetime singleton as default."""
    return Container(
        register_if_missing=True,
        autoregister_default_lifetime=Lifetime.SINGLETON,
    )


@pytest.fixture()
def container_no_autoregister() -> Container:
    """Container with auto-registration disabled."""
    return Container(register_if_missing=False)


# =============================================================================
# TestAsyncResolution - Basic aresolve() tests
# =============================================================================


class TestAsyncResolution:
    """Tests for basic aresolve() functionality."""

    async def test_aresolve_returns_instance(self, container: Container) -> None:
        """aresolve() returns an instance of the requested class."""
        instance = await container.aresolve(ServiceA)
        assert isinstance(instance, ServiceA)

    async def test_aresolve_transient_returns_different_instances(
        self,
        container: Container,
    ) -> None:
        """aresolve() with transient lifetime returns different instances."""
        instance1 = await container.aresolve(ServiceA)
        instance2 = await container.aresolve(ServiceA)
        assert instance1 is not instance2

    async def test_aresolve_singleton_returns_same_instance(
        self,
        container_singleton: Container,
    ) -> None:
        """aresolve() with singleton lifetime returns the same instance."""
        instance1 = await container_singleton.aresolve(ServiceA)
        instance2 = await container_singleton.aresolve(ServiceA)
        assert instance1 is instance2

    async def test_aresolve_auto_registers_class(self, container: Container) -> None:
        """aresolve() auto-registers unregistered classes."""

        class UnregisteredService:
            pass

        instance = await container.aresolve(UnregisteredService)
        assert isinstance(instance, UnregisteredService)

    async def test_aresolve_with_dependencies(self, container: Container) -> None:
        """aresolve() resolves transitive dependencies."""
        instance = await container.aresolve(ServiceB)
        assert isinstance(instance, ServiceB)
        assert isinstance(instance.service_a, ServiceA)


# =============================================================================
# TestAsyncFactory - Async factory tests
# =============================================================================


class TestAsyncFactory:
    """Tests for async factory functionality."""

    async def test_async_factory_is_detected(self, container: Container) -> None:
        """Async factory is auto-detected and used correctly."""

        async def create_service() -> ServiceA:
            await asyncio.sleep(0.001)
            return ServiceA(id="from-async-factory")

        container.register(ServiceA, factory=create_service)
        instance = await container.aresolve(ServiceA)

        assert isinstance(instance, ServiceA)
        assert instance.id == "from-async-factory"

    async def test_async_callable_class_factory(self, container: Container) -> None:
        """Async callable class is detected as async factory."""

        class AsyncServiceFactory:
            async def __call__(self) -> ServiceA:
                await asyncio.sleep(0.001)
                return ServiceA(id="from-async-class-factory")

        container.register(ServiceA, factory=AsyncServiceFactory)
        instance = await container.aresolve(ServiceA)

        assert isinstance(instance, ServiceA)
        assert instance.id == "from-async-class-factory"

    async def test_sync_resolve_on_async_factory_raises_error(
        self,
        container: Container,
    ) -> None:
        """Synchronous resolve() on async factory raises DIWireAsyncDependencyInSyncContextError."""

        async def create_service() -> ServiceA:
            return ServiceA()

        container.register(ServiceA, factory=create_service)

        with pytest.raises(DIWireAsyncDependencyInSyncContextError) as exc_info:
            container.resolve(ServiceA)

        assert exc_info.value.service_key.value is ServiceA

    async def test_explicit_is_async_override(self, container: Container) -> None:
        """Explicit is_async=True marks a sync factory as async."""

        def sync_factory() -> ServiceA:
            return ServiceA(id="sync-marked-async")

        container.register(ServiceA, factory=sync_factory, is_async=True)

        # Should raise when trying to resolve synchronously
        with pytest.raises(DIWireAsyncDependencyInSyncContextError):
            container.resolve(ServiceA)


# =============================================================================
# TestAsyncGeneratorFactory - Async generator cleanup tests
# =============================================================================


class TestAsyncGeneratorFactory:
    """Tests for async generator factory functionality."""

    async def test_async_generator_yields_instance(self, container: Container) -> None:
        """Async generator factory yields an instance."""
        cleanup_events: list[str] = []

        async def session_factory() -> AsyncGenerator[Session, None]:
            session = Session(id="async-generated")
            try:
                yield session
            finally:
                cleanup_events.append("cleaned")

        container.register(
            Session,
            factory=session_factory,
            scope="request",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        async with container.start_scope("request"):
            session = await container.aresolve(Session)
            assert session.id == "async-generated"
            assert cleanup_events == []

        assert cleanup_events == ["cleaned"]

    async def test_async_generator_cleanup_on_scope_exit(
        self,
        container: Container,
    ) -> None:
        """Async generator cleanup happens when scope exits."""
        cleanup_events: list[str] = []

        async def resource_factory() -> AsyncGenerator[ServiceA, None]:
            service = ServiceA(id="resource")
            try:
                yield service
            finally:
                await asyncio.sleep(0.001)  # Simulate async cleanup
                cleanup_events.append("resource-closed")

        container.register(
            ServiceA,
            factory=resource_factory,
            scope="test",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        async with container.start_scope("test"):
            service = await container.aresolve(ServiceA)
            assert service.id == "resource"

        assert cleanup_events == ["resource-closed"]

    async def test_async_generator_lifo_cleanup_order(
        self,
        container: Container,
    ) -> None:
        """Multiple async generators clean up in LIFO order."""
        cleanup_events: list[str] = []

        async def first_factory() -> AsyncGenerator[Session, None]:
            try:
                yield Session(id="first")
            finally:
                cleanup_events.append("first")

        async def second_factory() -> AsyncGenerator[ServiceA, None]:
            try:
                yield ServiceA(id="second")
            finally:
                cleanup_events.append("second")

        container.register(
            Session,
            factory=first_factory,
            scope="test",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )
        container.register(
            ServiceA,
            factory=second_factory,
            scope="test",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        async with container.start_scope("test"):
            await container.aresolve(Session)
            await container.aresolve(ServiceA)

        # LIFO order: second (last in) should be first out
        assert cleanup_events == ["second", "first"]

    async def test_async_generator_cleanup_on_exception(
        self,
        container: Container,
    ) -> None:
        """Async generator cleanup happens even when exception occurs."""
        cleanup_events: list[str] = []

        async def resource_factory() -> AsyncGenerator[ServiceA, None]:
            try:
                yield ServiceA()
            finally:
                cleanup_events.append("cleaned-on-error")

        container.register(
            ServiceA,
            factory=resource_factory,
            scope="test",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with pytest.raises(ValueError, match="test error"):
            async with container.start_scope("test"):
                await container.aresolve(ServiceA)
                raise ValueError("test error")

        assert cleanup_events == ["cleaned-on-error"]

    async def test_async_generator_without_scope_raises_error(
        self,
        container: Container,
    ) -> None:
        """Async generator factory without scope raises DIWireAsyncGeneratorFactoryWithoutScopeError."""

        async def resource_factory() -> AsyncGenerator[ServiceA, None]:
            yield ServiceA()

        container.register(ServiceA, factory=resource_factory, lifetime=Lifetime.TRANSIENT)

        with pytest.raises(DIWireAsyncGeneratorFactoryWithoutScopeError) as exc_info:
            await container.aresolve(ServiceA)

        assert exc_info.value.service_key.value is ServiceA

    async def test_async_generator_that_does_not_yield_raises_error(
        self,
        container: Container,
    ) -> None:
        """Async generator factory that doesn't yield raises DIWireAsyncGeneratorFactoryDidNotYieldError."""

        async def empty_factory() -> AsyncGenerator[ServiceA, None]:
            return
            yield  # Make it an async generator  # pyrefly: ignore[unreachable]

        container.register(
            ServiceA,
            factory=empty_factory,
            scope="test",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with pytest.raises(DIWireAsyncGeneratorFactoryDidNotYieldError) as exc_info:
            async with container.start_scope("test"):
                await container.aresolve(ServiceA)

        assert exc_info.value.service_key.value is ServiceA


# =============================================================================
# TestAsyncScope - Async scope context manager tests
# =============================================================================


class TestAsyncScope:
    """Tests for async scope context manager."""

    async def test_async_context_manager_sets_scope(self, container: Container) -> None:
        """async with container.start_scope() sets the current scope."""
        assert _current_scope.get() is None

        async with container.start_scope("test"):
            scope = _current_scope.get()
            assert scope is not None
            assert scope.contains_scope("test")

        assert _current_scope.get() is None

    async def test_async_scoped_singleton_caching(self, container: Container) -> None:
        """Async scoped singletons are cached within the scope."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        async with container.start_scope("request"):
            session1 = await container.aresolve(Session)
            session2 = await container.aresolve(Session)
            assert session1 is session2

    async def test_async_nested_scopes(self, container: Container) -> None:
        """Nested async scopes work correctly."""
        container.register(Session, scope="child", lifetime=Lifetime.SCOPED_SINGLETON)

        async with container.start_scope("parent") as parent:
            async with parent.start_scope("child"):
                session = await container.aresolve(Session)
                assert isinstance(session, Session)


# =============================================================================
# TestParallelResolution - Parallel async resolution tests
# =============================================================================


class TestParallelResolution:
    """Tests for parallel async dependency resolution."""

    async def test_parallel_deps_resolved_concurrently(
        self,
        container: Container,
    ) -> None:
        """Dependencies are resolved in parallel via asyncio.gather()."""

        async def slow_factory_a() -> ServiceA:
            await asyncio.sleep(0.05)
            return ServiceA(id="slow-a")

        async def slow_factory_b() -> ServiceB:
            await asyncio.sleep(0.05)
            service_a = ServiceA(id="slow-b-dep")
            return ServiceB(service_a=service_a)

        @dataclass
        class ServiceWithManyAsyncDeps:
            a: ServiceA
            b: ServiceB

        container.register(ServiceA, factory=slow_factory_a)
        container.register(ServiceB, factory=slow_factory_b)

        start = time.perf_counter()
        result = await container.aresolve(ServiceWithManyAsyncDeps)
        elapsed = time.perf_counter() - start

        assert isinstance(result, ServiceWithManyAsyncDeps)
        # If resolved in parallel, should be ~50ms. If sequential, ~100ms+.
        assert elapsed < 0.15, f"Expected parallel resolution, but took {elapsed:.3f}s"

    async def test_mixed_sync_async_chain(self, container: Container) -> None:
        """Mixed sync and async dependency chains work correctly."""

        async def async_factory() -> ServiceA:
            return ServiceA(id="async")

        container.register(ServiceA, factory=async_factory)

        result = await container.aresolve(MixedService)
        assert isinstance(result, MixedService)
        assert result.sync.value == "sync"
        assert result.async_dep.id == "async"


# =============================================================================
# TestAsyncInjected - AsyncInjected wrapper tests
# =============================================================================


class TestAsyncInjected:
    """Tests for AsyncInjected wrapper."""

    async def test_aresolve_async_function_returns_async_injected(
        self,
        container: Container,
    ) -> None:
        """aresolve() on async function returns AsyncInjected."""

        async def handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = await container.aresolve(handler)
        assert isinstance(injected, AsyncInjected)

    async def test_async_injected_resolves_transient_deps(
        self,
        container: Container,
    ) -> None:
        """AsyncInjected resolves transient deps fresh each call."""

        async def handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = await container.aresolve(handler)

        result1 = await injected()
        result2 = await injected()

        assert isinstance(result1, ServiceA)
        assert isinstance(result2, ServiceA)
        assert result1 is not result2

    async def test_async_injected_resolves_singleton_deps(
        self,
        container_singleton: Container,
    ) -> None:
        """AsyncInjected resolves singleton deps to same instance."""

        async def handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = await container_singleton.aresolve(handler)

        result1 = await injected()
        result2 = await injected()

        assert result1 is result2

    async def test_async_injected_preserves_metadata(self, container: Container) -> None:
        """AsyncInjected preserves function metadata."""

        async def my_handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            """Handler docstring."""
            return service

        injected = await container.aresolve(my_handler)

        assert injected.__name__ == "my_handler"
        assert injected.__doc__ == "Handler docstring."
        assert injected.__wrapped__ is my_handler

    async def test_async_injected_signature_filters_di_params(
        self,
        container: Container,
    ) -> None:
        """AsyncInjected signature excludes FromDI parameters."""

        async def handler(
            value: int,
            service: Annotated[ServiceA, FromDI()],
        ) -> int:
            return value

        injected = await container.aresolve(handler)
        sig = signature(injected)

        param_names = list(sig.parameters.keys())
        assert param_names == ["value"]
        assert "service" not in param_names

    async def test_async_injected_repr(self, container: Container) -> None:
        """AsyncInjected has informative repr."""

        async def my_handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = await container.aresolve(my_handler)
        repr_str = repr(injected)

        assert "AsyncInjected" in repr_str
        assert "my_handler" in repr_str


# =============================================================================
# TestAsyncScopedInjected - AsyncScopedInjected wrapper tests
# =============================================================================


class TestAsyncScopedInjected:
    """Tests for AsyncScopedInjected wrapper."""

    async def test_aresolve_async_function_with_scope_returns_async_scoped_injected(
        self,
        container: Container,
    ) -> None:
        """aresolve() with scope parameter returns AsyncScopedInjected."""

        async def handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = await container.aresolve(handler, scope="request")
        assert isinstance(injected, AsyncScopedInjected)

    async def test_async_scoped_injected_fresh_scope_per_call(
        self,
        container: Container,
    ) -> None:
        """AsyncScopedInjected creates a fresh scope per call."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        async def handler(session: Annotated[Session, FromDI()]) -> Session:
            return session

        injected = await container.aresolve(handler, scope="request")

        result1 = await injected()
        result2 = await injected()

        # Different calls get different sessions (different scopes)
        assert result1.id != result2.id

    async def test_async_scoped_injected_shares_instance_within_call(
        self,
        container: Container,
    ) -> None:
        """AsyncScopedInjected shares scoped instances within a single call."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        async def handler(
            x: Annotated[ServiceXForScope, FromDI()],
            y: Annotated[ServiceYForScope, FromDI()],
        ) -> tuple[ServiceXForScope, ServiceYForScope]:
            return x, y

        injected = await container.aresolve(handler, scope="request")

        x, y = await injected()

        # Same session within the same call
        assert x.session.id == y.session.id

    async def test_async_scoped_injected_repr(self, container: Container) -> None:
        """AsyncScopedInjected has informative repr."""

        async def my_handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = await container.aresolve(my_handler, scope="request")
        repr_str = repr(injected)

        assert "AsyncScopedInjected" in repr_str
        assert "request" in repr_str


# =============================================================================
# TestAsyncConcurrency - Task isolation and concurrent resolution tests
# =============================================================================


class TestAsyncConcurrency:
    """Tests for async task isolation and concurrency."""

    async def test_async_task_isolation(self, container: Container) -> None:
        """Each async task has isolated scope context."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        results: dict[str, str] = {}

        async def worker(worker_id: str) -> None:
            async with container.start_scope("request"):
                session = await container.aresolve(Session)
                results[worker_id] = session.id
                await asyncio.sleep(0.01)

        await asyncio.gather(*[worker(f"task-{i}") for i in range(5)])

        # Each task should have unique session
        session_ids = list(results.values())
        assert len(session_ids) == len(set(session_ids))

    async def test_concurrent_scope_contexts(self, container: Container) -> None:
        """Concurrent async scopes don't interfere with each other."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        scope_ids: dict[str, str] = {}

        async def worker(worker_id: str) -> None:
            async with container.start_scope("request"):
                scope_id = _current_scope.get()
                scope_ids[worker_id] = scope_id  # type: ignore[assignment]
                await asyncio.sleep(0.01)

        await asyncio.gather(*[worker(f"task-{i}") for i in range(5)])

        # Each task should have unique scope ID
        ids = list(scope_ids.values())
        assert len(ids) == len(set(ids))

    async def test_circular_detection_isolation(self, container: Container) -> None:
        """Circular detection is isolated per async task."""
        circular_errors: list[DIWireCircularDependencyError] = []
        normal_results: list[ServiceA] = []

        async def resolve_circular() -> None:
            try:
                await container.aresolve(CircularForAsync_A)
            except DIWireCircularDependencyError as e:
                circular_errors.append(e)

        async def resolve_normal() -> None:
            result = await container.aresolve(ServiceA)
            normal_results.append(result)

        # Mix circular and normal resolutions
        tasks = []
        for i in range(10):
            if i % 2 == 0:
                tasks.append(resolve_circular())
            else:
                tasks.append(resolve_normal())

        await asyncio.gather(*tasks)

        # Circular errors in circular tasks shouldn't affect normal tasks
        assert len(circular_errors) == 5
        assert len(normal_results) == 5

    async def test_concurrent_async_singleton_resolution(
        self,
        container_singleton: Container,
    ) -> None:
        """Concurrent async singleton resolution returns same instance."""
        results: list[ServiceA] = []

        async def worker() -> None:
            instance = await container_singleton.aresolve(ServiceA)
            results.append(instance)

        await asyncio.gather(*[worker() for _ in range(10)])

        assert len(results) == 10
        # All should be the same instance
        assert all(r is results[0] for r in results)

    async def test_concurrent_async_transient_resolution(
        self,
        container: Container,
    ) -> None:
        """Concurrent async transient resolution returns different instances."""
        results: list[ServiceA] = []

        async def worker() -> None:
            instance = await container.aresolve(ServiceA)
            results.append(instance)

        await asyncio.gather(*[worker() for _ in range(10)])

        assert len(results) == 10
        # All should be different instances
        unique_ids = {r.id for r in results}
        assert len(unique_ids) == 10


# =============================================================================
# TestScopedContainerAsync - ScopedContainer.aresolve() tests
# =============================================================================


class TestScopedContainerAsync:
    """Tests for ScopedContainer.aresolve() method."""

    async def test_scoped_container_aresolve(self, container: Container) -> None:
        """ScopedContainer.aresolve() works correctly."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        async with container.start_scope("test") as scoped:
            session = await scoped.aresolve(Session)
            assert isinstance(session, Session)

    async def test_scoped_container_aresolve_after_exit_raises(
        self,
        container: Container,
    ) -> None:
        """ScopedContainer.aresolve() after scope exit raises error."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        async with container.start_scope("test") as scoped:
            pass

        from diwire.exceptions import DIWireScopeMismatchError

        with pytest.raises(DIWireScopeMismatchError):
            await scoped.aresolve(Session)


# =============================================================================
# TestAsyncResolveOnSyncFunction - aresolve() on sync functions
# =============================================================================


class TestAsyncResolveOnSyncFunction:
    """Tests for aresolve() behavior on sync functions."""

    async def test_aresolve_sync_function_returns_injected(
        self,
        container: Container,
    ) -> None:
        """aresolve() on sync function returns Injected (not AsyncInjected)."""

        def sync_handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = await container.aresolve(sync_handler)

        # Sync function should return Injected, not AsyncInjected
        assert isinstance(injected, Injected)
        assert not isinstance(injected, AsyncInjected)  # type: ignore[unreachable]

    async def test_aresolve_sync_function_with_scope_returns_scoped_injected(
        self,
        container: Container,
    ) -> None:
        """aresolve() on sync function with scope returns ScopedInjected."""

        def sync_handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = await container.aresolve(sync_handler, scope="request")

        assert isinstance(injected, ScopedInjected)
        assert not isinstance(injected, AsyncScopedInjected)  # type: ignore[unreachable]


# =============================================================================
# TestSyncResolveReturnsAsyncInjected - resolve() returns AsyncInjected for async functions
# =============================================================================


class TestSyncResolveReturnsAsyncInjected:
    """Tests for resolve() returning AsyncInjected for async functions."""

    def test_resolve_returns_async_injected_for_async_function(
        self,
        container: Container,
    ) -> None:
        """resolve() on async function returns AsyncInjected."""

        async def handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = container.resolve(handler)
        assert isinstance(injected, AsyncInjected)

    def test_resolve_returns_async_scoped_injected_with_scope(
        self,
        container: Container,
    ) -> None:
        """resolve() on async function with scope returns AsyncScopedInjected."""

        async def handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = container.resolve(handler, scope="request")
        assert isinstance(injected, AsyncScopedInjected)

    async def test_resolve_async_function_with_async_factory(
        self,
        container: Container,
    ) -> None:
        """resolve() on async handler correctly handles async factory dependencies."""

        async def create_service() -> ServiceA:
            return ServiceA(id="from-async-factory")

        async def handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        container.register(ServiceA, factory=create_service)
        injected = container.resolve(handler)

        assert isinstance(injected, AsyncInjected)
        result = await injected()
        assert result.id == "from-async-factory"

    async def test_fastapi_style_integration(self, container: Container) -> None:
        """FastAPI-style: resolve async handler with async factory dependency."""

        async def get_session() -> Session:
            return Session(id="session-123")

        async def handler(
            request: str,
            session: Annotated[Session, FromDI()],
        ) -> dict[str, str]:
            return {"session_id": session.id}

        container.register(Session, factory=get_session)
        resolved_handler = container.resolve(handler)

        assert isinstance(resolved_handler, AsyncInjected)
        result = await resolved_handler("dummy-request")
        assert result == {"session_id": "session-123"}

    def test_resolve_sync_function_still_returns_injected(
        self,
        container: Container,
    ) -> None:
        """resolve() on sync function still returns Injected (not AsyncInjected)."""

        def sync_handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = container.resolve(sync_handler)

        assert isinstance(injected, Injected)
        assert not isinstance(injected, AsyncInjected)  # type: ignore[unreachable]

    def test_resolve_sync_function_with_scope_still_returns_scoped_injected(
        self,
        container: Container,
    ) -> None:
        """resolve() on sync function with scope still returns ScopedInjected."""

        def sync_handler(service: Annotated[ServiceA, FromDI()]) -> ServiceA:
            return service

        injected = container.resolve(sync_handler, scope="request")

        assert isinstance(injected, ScopedInjected)
        assert not isinstance(injected, AsyncScopedInjected)  # type: ignore[unreachable]


# =============================================================================
# TestAsyncMissingCoverage - Tests for missing async coverage
# =============================================================================


class TestAsyncMissingCoverage:
    """Tests for async resolution missing coverage."""

    @pytest.mark.asyncio
    async def test_aresolve_instance_non_scoped(self) -> None:
        """Async resolve instance registration stores in _singletons."""
        from diwire.registry import Registration
        from diwire.service_key import ServiceKey

        container = Container(register_if_missing=False, auto_compile=False)

        instance = ServiceA()
        service_key = ServiceKey.from_value(ServiceA)
        container._registry[service_key] = Registration(
            service_key=service_key,
            instance=instance,
            lifetime=Lifetime.SINGLETON,
            scope=None,
        )

        resolved = await container.aresolve(ServiceA)
        assert resolved is instance
        assert service_key in container._singletons

    @pytest.mark.asyncio
    async def test_aresolve_sync_generator_without_scope(self) -> None:
        """Sync generator factory in aresolve without scope raises error."""
        from diwire.exceptions import DIWireGeneratorFactoryWithoutScopeError

        container = Container()

        def generator_factory() -> Generator[ServiceA, None, None]:
            yield ServiceA()

        container.register(
            ServiceA,
            factory=generator_factory,
            lifetime=Lifetime.TRANSIENT,
        )

        with pytest.raises(DIWireGeneratorFactoryWithoutScopeError):
            await container.aresolve(ServiceA)

    @pytest.mark.asyncio
    async def test_aresolve_sync_generator_no_yield(self) -> None:
        """Sync generator that doesn't yield in aresolve raises error."""
        from diwire.exceptions import DIWireGeneratorFactoryDidNotYieldError

        container = Container()

        def empty_generator() -> Generator[None, None, None]:
            return
            yield  # Make it a generator  # pyrefly: ignore[unreachable]

        container.register(
            ServiceA,
            factory=empty_generator,
            scope="request",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        async with container.start_scope("request"):
            with pytest.raises(DIWireGeneratorFactoryDidNotYieldError):
                await container.aresolve(ServiceA)

    @pytest.mark.asyncio
    async def test_aget_resolved_deps_ignored_type_missing(self) -> None:
        """Async resolve with ignored type without default raises missing deps error."""
        from diwire.exceptions import DIWireMissingDependenciesError

        container = Container(register_if_missing=False, auto_compile=False)

        class ServiceWithStr:
            def __init__(self, name: str) -> None:  # str is ignored, no default
                self.name = name

        container.register(ServiceWithStr, lifetime=Lifetime.TRANSIENT)

        with pytest.raises(DIWireMissingDependenciesError):
            await container.aresolve(ServiceWithStr)

    @pytest.mark.asyncio
    async def test_aget_resolved_deps_uses_async_cache(self) -> None:
        """Async resolution uses pre-built async deps cache."""
        from diwire.service_key import ServiceKey

        container = Container(auto_compile=False)

        async def async_factory() -> ServiceA:
            return ServiceA()

        container.register(
            ServiceA,
            factory=async_factory,
            lifetime=Lifetime.TRANSIENT,
        )
        container.register(ServiceB, lifetime=Lifetime.TRANSIENT)
        container.compile()

        # The cache should have ServiceB -> {ServiceA} since ServiceA is async
        service_key_b = ServiceKey.from_value(ServiceB)
        assert service_key_b in container._async_deps_cache

        result = await container.aresolve(ServiceB)
        assert isinstance(result.service_a, ServiceA)
