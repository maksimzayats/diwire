"""Tests for container_context module - global container context using contextvars."""

from __future__ import annotations

import asyncio
import inspect
import threading
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any, cast

import pytest

from diwire import Container, Injected, Lifetime, container_context
from diwire.container_context import (
    _AsyncContextInjected,
    _AsyncContextScopedInjected,
    _ContainerContextProxy,
    _ContextInjected,
    _ContextScopedInjected,
    _current_container,
    _thread_local_fallback,
)
from diwire.exceptions import DIWireContainerNotSetError


@dataclass
class ServiceA:
    """Test service A."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class ServiceB:
    """Test service B."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class ServiceWithDep:
    """Service with a dependency."""

    service_a: ServiceA


# Module-level circular dependency classes for PEP 563 compatibility
# Using regular classes with __init__ (not dataclasses) for proper circular detection
class _CircularA:
    def __init__(self, b: _CircularB) -> None:
        self.b = b


class _CircularB:
    def __init__(self, a: _CircularA) -> None:
        self.a = a


# ============================================================================
# DIWireContainerNotSetError Tests
# ============================================================================


class TestDIWireContainerNotSetError:
    """Tests for DIWireContainerNotSetError exception."""

    def test_container_not_set_error_inherits_from_diwire_error(self) -> None:
        """DIWireContainerNotSetError inherits from DIWireError."""
        from diwire.exceptions import DIWireError

        assert issubclass(DIWireContainerNotSetError, DIWireError)

    def test_get_current_without_container_raises_error(self) -> None:
        """get_current() raises DIWireContainerNotSetError when no container set."""
        proxy = _ContainerContextProxy()
        # Ensure no container is set
        token = _current_container.set(None)
        try:
            with pytest.raises(DIWireContainerNotSetError) as exc_info:
                proxy.get_current()

            assert "No container set in current context" in str(exc_info.value)
            assert "set_current" in str(exc_info.value)
        finally:
            _current_container.reset(token)

    def test_resolve_type_without_container_raises_error(self) -> None:
        """resolve(SomeType) raises DIWireContainerNotSetError when no container set."""
        proxy = _ContainerContextProxy()
        token = _current_container.set(None)
        try:
            with pytest.raises(DIWireContainerNotSetError):
                proxy.resolve(ServiceA)
        finally:
            _current_container.reset(token)


# ============================================================================
# Basic Proxy Functionality Tests
# ============================================================================


class TestBasicProxyFunctionality:
    """Tests for basic _ContainerContextProxy functionality."""

    def test_set_current_returns_token(self) -> None:
        """set_current() returns a token for reset."""
        proxy = _ContainerContextProxy()
        container = Container()

        token = proxy.set_current(container)
        try:
            assert token is not None
            assert proxy.get_current() is container
        finally:
            proxy.reset(token)

    def test_get_current_returns_container(self) -> None:
        """get_current() returns the current container."""
        proxy = _ContainerContextProxy()
        container = Container()

        token = proxy.set_current(container)
        try:
            assert proxy.get_current() is container
        finally:
            proxy.reset(token)

    def test_reset_restores_previous_value(self) -> None:
        """reset() restores the previous container value."""
        proxy = _ContainerContextProxy()
        container1 = Container()
        container2 = Container()

        token1 = proxy.set_current(container1)
        try:
            token2 = proxy.set_current(container2)
            assert proxy.get_current() is container2

            proxy.reset(token2)
            assert proxy.get_current() is container1
        finally:
            proxy.reset(token1)

    def test_reset_to_none(self) -> None:
        """reset() can restore to no container."""
        proxy = _ContainerContextProxy()
        container = Container()

        # Start with no container
        initial_token = _current_container.set(None)
        try:
            token = proxy.set_current(container)
            assert proxy.get_current() is container

            proxy.reset(token)
            with pytest.raises(DIWireContainerNotSetError):
                proxy.get_current()
        finally:
            _current_container.reset(initial_token)

    def test_singleton_container_context_instance(self) -> None:
        """container_context is a singleton instance."""
        from diwire import container_context as ctx1
        from diwire.container_context import container_context as ctx2

        assert ctx1 is ctx2


# ============================================================================
# Proxy Method Delegation Tests
# ============================================================================


class TestProxyMethodDelegation:
    """Tests for proxy methods that delegate to the current container."""

    def test_register_delegates_to_container(self) -> None:
        """register() delegates to the current container."""
        container = Container(autoregister=False)
        token = container_context.set_current(container)
        try:
            container_context.register(ServiceA, lifetime=Lifetime.SINGLETON)

            # Verify registration worked
            service = container.resolve(ServiceA)
            assert isinstance(service, ServiceA)
        finally:
            container_context.reset(token)

    def test_enter_scope_delegates_to_container(self) -> None:
        """enter_scope() delegates to the current container."""
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)

        token = container_context.set_current(container)
        try:
            with container_context.enter_scope("request"):
                service = container.resolve(ServiceA)
                assert isinstance(service, ServiceA)
        finally:
            container_context.reset(token)

    def test_compile_delegates_to_container(self) -> None:
        """compile() delegates to the current container."""
        container = Container(auto_compile=False)
        container.register(ServiceA, lifetime=Lifetime.SINGLETON)

        token = container_context.set_current(container)
        try:
            assert not container._is_compiled
            container_context.compile()
            assert container._is_compiled
        finally:
            container_context.reset(token)

    @pytest.mark.asyncio
    async def test_aresolve_delegates_to_container(self) -> None:
        """aresolve() delegates to the current container."""
        container = Container()

        token = container_context.set_current(container)
        try:
            service = await container_context.aresolve(ServiceA)
            assert isinstance(service, ServiceA)
        finally:
            container_context.reset(token)


# ============================================================================
# Register Decorator Tests
# ============================================================================


class TestRegisterDecoratorPattern:
    """Tests for container_context.register decorator usage."""

    def test_register_decorator_registers_class(self) -> None:
        """@container_context.register on a class should register it."""
        container = Container(autoregister=False)
        token = container_context.set_current(container)
        try:

            @container_context.register
            class MyService:
                pass

            instance = container.resolve(MyService)
            assert isinstance(instance, MyService)
        finally:
            container_context.reset(token)

    def test_register_decorator_returns_original_class(self) -> None:
        """@container_context.register should return the original class unchanged."""
        container = Container(autoregister=False)
        token = container_context.set_current(container)
        try:

            @container_context.register
            class MyService:
                pass

            assert MyService.__name__ == "MyService"
            assert hasattr(MyService, "__init__")
        finally:
            container_context.reset(token)

    def test_register_decorator_with_lifetime_singleton(self) -> None:
        """@container_context.register(lifetime=SINGLETON) should create singletons."""
        container = Container(autoregister=False)
        token = container_context.set_current(container)
        try:

            @container_context.register(lifetime=Lifetime.SINGLETON)
            class MySingleton:
                pass

            instance1 = container.resolve(MySingleton)
            instance2 = container.resolve(MySingleton)
            assert instance1 is instance2
        finally:
            container_context.reset(token)

    def test_register_factory_decorator_infers_type(self) -> None:
        """@container_context.register on a function should infer return type."""
        container = Container(autoregister=False)
        token = container_context.set_current(container)
        try:

            @container_context.register
            def create_service() -> ServiceA:
                return ServiceA(id="factory")

            assert create_service.__name__ == "create_service"
            instance = container.resolve(ServiceA)
            assert instance.id == "factory"
        finally:
            container_context.reset(token)


# ============================================================================
# Decorator Pattern Tests - Sync Functions
# ============================================================================


class TestDecoratorPatternSync:
    """Tests for decorator pattern with sync functions."""

    def test_resolve_decorator_without_scope_returns_context_injected(self) -> None:
        """@container_context.resolve() returns _ContextInjected for sync."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            assert isinstance(handler, _ContextInjected)
        finally:
            container_context.reset(token)

    def test_resolve_decorator_with_scope_returns_context_scoped_injected(self) -> None:
        """@container_context.resolve(scope="...") returns _ContextScopedInjected."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve(scope="request")
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            assert isinstance(handler, _ContextScopedInjected)
        finally:
            container_context.reset(token)

    def test_resolve_direct_call_with_function(self) -> None:
        """container_context.resolve(func) works."""
        container = Container()
        token = container_context.set_current(container)
        try:

            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            injected = container_context.resolve(handler)
            assert isinstance(injected, _ContextInjected)
        finally:
            container_context.reset(token)

    def test_resolve_direct_call_with_function_and_scope(self) -> None:
        """container_context.resolve(func, scope="...") works."""
        container = Container()
        token = container_context.set_current(container)
        try:

            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            injected = container_context.resolve(handler, scope="request")
            assert isinstance(injected, _ContextScopedInjected)
        finally:
            container_context.reset(token)

    def test_decorated_function_resolves_dependencies(self) -> None:
        """Decorated function resolves Injected dependencies."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            result = handler()
            assert isinstance(result, ServiceA)
        finally:
            container_context.reset(token)

    def test_decorated_function_passes_caller_args(self) -> None:
        """Decorated function passes non-injected args correctly."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                value: int,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[int, ServiceA]:
                return value, service

            result_value, result_service = handler(42)
            assert result_value == 42
            assert isinstance(result_service, ServiceA)
        finally:
            container_context.reset(token)

    def test_decorated_function_with_scoped_singleton(self) -> None:
        """Decorated function with scope creates scope per call."""
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)

        token = container_context.set_current(container)
        try:

            @container_context.resolve(scope="request")
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            result1 = handler()
            result2 = handler()
            # Different calls should produce different scoped instances
            assert result1.id != result2.id
        finally:
            container_context.reset(token)


# ============================================================================
# Decorator Pattern Tests - Async Functions
# ============================================================================


class TestDecoratorPatternAsync:
    """Tests for decorator pattern with async functions."""

    def test_resolve_decorator_without_scope_returns_async_context_injected(self) -> None:
        """@container_context.resolve() returns _AsyncContextInjected for async."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            assert isinstance(handler, _AsyncContextInjected)
        finally:
            container_context.reset(token)

    def test_resolve_decorator_with_scope_returns_async_context_scoped_injected(self) -> None:
        """@container_context.resolve(scope="...") returns _AsyncContextScopedInjected."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve(scope="request")
            async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            assert isinstance(handler, _AsyncContextScopedInjected)
        finally:
            container_context.reset(token)

    @pytest.mark.asyncio
    async def test_async_decorated_function_resolves_dependencies(self) -> None:
        """Async decorated function resolves Injected dependencies."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            result = await handler()
            assert isinstance(result, ServiceA)
        finally:
            container_context.reset(token)

    @pytest.mark.asyncio
    async def test_async_decorated_function_with_scope(self) -> None:
        """Async decorated function with scope creates scope per call."""
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)

        token = container_context.set_current(container)
        try:

            @container_context.resolve(scope="request")
            async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            result1 = await handler()
            result2 = await handler()
            # Different calls should produce different scoped instances
            assert result1.id != result2.id
        finally:
            container_context.reset(token)

    @pytest.mark.asyncio
    async def test_async_decorated_function_passes_args(self) -> None:
        """Async decorated function passes non-injected args correctly."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve(scope="request")
            async def handler(
                value: int,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[int, ServiceA]:
                return value, service

            result_value, result_service = await handler(42)
            assert result_value == 42
            assert isinstance(result_service, ServiceA)
        finally:
            container_context.reset(token)


# ============================================================================
# Lazy Container Lookup Tests
# ============================================================================


class TestLazyContainerLookup:
    """Tests for lazy container lookup - container resolved at call time, not decoration time."""

    def test_decorator_applied_before_container_set(self) -> None:
        """Decorator can be applied before container is set."""
        # Clear any existing container
        initial_token = _current_container.set(None)
        try:
            # Apply decorator BEFORE container is set
            @container_context.resolve(scope="request")
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            # Should create wrapper without error
            assert isinstance(handler, _ContextScopedInjected)

            # Now set the container
            container = Container()
            token = container_context.set_current(container)
            try:
                # Now calling the handler should work
                result = handler()
                assert isinstance(result, ServiceA)
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)

    def test_async_decorator_applied_before_container_set(self) -> None:
        """Async decorator can be applied before container is set."""
        initial_token = _current_container.set(None)
        try:

            @container_context.resolve(scope="request")
            async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            assert isinstance(handler, _AsyncContextScopedInjected)

            container = Container()
            token = container_context.set_current(container)
            try:
                result = asyncio.run(handler())
                assert isinstance(result, ServiceA)
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)

    def test_handler_uses_current_container_at_call_time(self) -> None:
        """Handler uses the container that is current when called, not when decorated."""
        initial_token = _current_container.set(None)
        try:

            @container_context.resolve()
            def handler(service: Annotated[ServiceA, Injected()]) -> str:
                return service.id

            # First container
            container1 = Container()
            container1.register(ServiceA, instance=ServiceA(id="container1"))

            token1 = container_context.set_current(container1)
            result1 = handler()
            container_context.reset(token1)

            # Second container
            container2 = Container()
            container2.register(ServiceA, instance=ServiceA(id="container2"))

            token2 = container_context.set_current(container2)
            result2 = handler()
            container_context.reset(token2)

            # Each call should have used the current container at that time
            assert result1 == "container1"
            assert result2 == "container2"
        finally:
            _current_container.reset(initial_token)


# ============================================================================
# Signature Tests
# ============================================================================


class TestSignatureHandling:
    """Tests for signature handling - Injected parameters should be hidden."""

    def test_signature_hides_fromdi_params_sync(self) -> None:
        """Signature hides Injected parameters for sync functions."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                value: int,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[int, ServiceA]:
                return value, service

            sig = inspect.signature(handler)
            param_names = list(sig.parameters.keys())
            assert param_names == ["value"]
            assert "service" not in param_names
        finally:
            container_context.reset(token)

    def test_signature_hides_fromdi_params_async(self) -> None:
        """Signature hides Injected parameters for async functions."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            async def handler(
                value: int,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[int, ServiceA]:
                return value, service

            sig = inspect.signature(handler)
            param_names = list(sig.parameters.keys())
            assert param_names == ["value"]
            assert "service" not in param_names
        finally:
            container_context.reset(token)

    def test_signature_hides_fromdi_params_scoped(self) -> None:
        """Signature hides Injected parameters for scoped wrappers."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve(scope="request")
            def handler(
                value: int,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[int, ServiceA]:
                return value, service

            sig = inspect.signature(handler)
            param_names = list(sig.parameters.keys())
            assert param_names == ["value"]
        finally:
            container_context.reset(token)

    def test_signature_built_at_decoration_time_not_call_time(self) -> None:
        """Signature is built at decoration time, even before container is set."""
        initial_token = _current_container.set(None)
        try:

            @container_context.resolve(scope="request")
            def handler(
                value: int,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[int, ServiceA]:
                return value, service

            # Signature should be available even without container
            sig = inspect.signature(handler)
            param_names = list(sig.parameters.keys())
            assert param_names == ["value"]
        finally:
            _current_container.reset(initial_token)


# ============================================================================
# Metadata Preservation Tests
# ============================================================================


class TestMetadataPreservation:
    """Tests for function metadata preservation."""

    def test_preserves_function_name(self) -> None:
        """Wrapper preserves __name__."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def my_handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            assert my_handler.__name__ == "my_handler"
        finally:
            container_context.reset(token)

    def test_preserves_docstring(self) -> None:
        """Wrapper preserves __doc__."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                """This is my docstring."""
                return service

            assert handler.__doc__ == "This is my docstring."
        finally:
            container_context.reset(token)

    def test_preserves_wrapped_attribute(self) -> None:
        """Wrapper preserves __wrapped__."""
        container = Container()
        token = container_context.set_current(container)
        try:

            def original_handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            wrapped = container_context.resolve(original_handler)
            assert wrapped.__wrapped__ is original_handler
        finally:
            container_context.reset(token)

    def test_context_injected_repr(self) -> None:
        """_ContextInjected has informative repr."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            assert "_ContextInjected" in repr(handler)
        finally:
            container_context.reset(token)

    def test_context_scoped_injected_repr(self) -> None:
        """_ContextScopedInjected has informative repr."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve(scope="request")
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            assert "_ContextScopedInjected" in repr(handler)
            assert "request" in repr(handler)
        finally:
            container_context.reset(token)


# ============================================================================
# Direct Type Resolution Tests
# ============================================================================


class TestDirectTypeResolution:
    """Tests for direct type resolution via container_context.resolve(Type)."""

    def test_resolve_type_directly(self) -> None:
        """container_context.resolve(Type) resolves the type."""
        container = Container()
        token = container_context.set_current(container)
        try:
            service = container_context.resolve(ServiceA)
            assert isinstance(service, ServiceA)
        finally:
            container_context.reset(token)

    def test_resolve_type_with_scope(self) -> None:
        """container_context.resolve(Type, scope="...") works."""
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)

        token = container_context.set_current(container)
        try:
            with container_context.enter_scope("request"):
                service = container_context.resolve(ServiceA, scope="request")
                assert isinstance(service, ServiceA)
        finally:
            container_context.reset(token)

    def test_resolve_registered_instance(self) -> None:
        """container_context.resolve() returns registered instance."""
        container = Container()
        specific_service = ServiceA(id="specific-123")
        container.register(ServiceA, instance=specific_service)

        token = container_context.set_current(container)
        try:
            service = container_context.resolve(ServiceA)
            assert service.id == "specific-123"
        finally:
            container_context.reset(token)


# ============================================================================
# Thread/Context Isolation Tests
# ============================================================================


class TestContextIsolation:
    """Tests for context variable isolation across threads and async tasks."""

    def test_different_threads_have_isolated_containers(self) -> None:
        """Each thread can have its own container via contextvars."""
        results: dict[str, str] = {}
        errors: list[Exception] = []

        def worker(worker_id: str, container: Container) -> None:
            try:
                token = container_context.set_current(container)
                try:
                    service = container_context.resolve(ServiceA)
                    results[worker_id] = service.id
                finally:
                    container_context.reset(token)
            except Exception as e:
                errors.append(e)

        # Create containers with specific instances
        container1 = Container()
        container1.register(ServiceA, instance=ServiceA(id="thread1"))

        container2 = Container()
        container2.register(ServiceA, instance=ServiceA(id="thread2"))

        t1 = threading.Thread(target=worker, args=("t1", container1))
        t2 = threading.Thread(target=worker, args=("t2", container2))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors
        assert results["t1"] == "thread1"
        assert results["t2"] == "thread2"

    def test_async_tasks_have_isolated_containers(self) -> None:
        """Each async task can have its own container via contextvars."""
        results: dict[str, str] = {}

        async def worker(task_id: str, container: Container) -> None:
            token = container_context.set_current(container)
            try:
                await asyncio.sleep(0.01)  # Allow interleaving
                service = container_context.resolve(ServiceA)
                results[task_id] = service.id
            finally:
                container_context.reset(token)

        async def run_tasks() -> None:
            container1 = Container()
            container1.register(ServiceA, instance=ServiceA(id="task1"))

            container2 = Container()
            container2.register(ServiceA, instance=ServiceA(id="task2"))

            await asyncio.gather(
                worker("task1", container1),
                worker("task2", container2),
            )

        asyncio.run(run_tasks())

        assert results["task1"] == "task1"
        assert results["task2"] == "task2"


# ============================================================================
# Thread-Local Fallback Isolation Tests
# ============================================================================


class TestThreadLocalFallbackIsolation:
    """Tests for thread-local fallback isolation to prevent cross-thread container leakage."""

    def test_thread_local_fallback_isolated_between_threads(self) -> None:
        """Direct thread-local access is isolated between threads."""
        from concurrent.futures import ThreadPoolExecutor

        results: dict[str, str | None] = {}

        def worker(thread_id: str) -> None:
            # Set thread-local container
            container = Container()
            container.register(ServiceA, instance=ServiceA(id=thread_id))
            _thread_local_fallback.container = container

            # Verify we can read back our own container
            local_container = getattr(_thread_local_fallback, "container", None)
            if local_container is not None:
                results[thread_id] = local_container.resolve(ServiceA).id
            else:
                results[thread_id] = None

        with ThreadPoolExecutor(max_workers=2) as executor:
            executor.submit(worker, "thread1")
            executor.submit(worker, "thread2")

        # Each thread should see its own container
        assert results["thread1"] == "thread1"
        assert results["thread2"] == "thread2"

    def test_concurrent_set_current_thread_isolation(self) -> None:
        """Multiple threads calling set_current see their own containers."""
        from concurrent.futures import ThreadPoolExecutor, wait

        results: dict[str, str] = {}
        errors: list[Exception] = []
        barrier = threading.Barrier(3)

        def worker(thread_id: str) -> None:
            try:
                container = Container()
                container.register(ServiceA, instance=ServiceA(id=thread_id))

                token = container_context.set_current(container)
                try:
                    # Wait for all threads to set their container
                    barrier.wait()

                    # Small delay to allow potential race conditions
                    import time

                    time.sleep(0.01)

                    # Each thread should see its own container
                    service = container_context.resolve(ServiceA)
                    results[thread_id] = service.id
                finally:
                    container_context.reset(token)
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(worker, "t1"),
                executor.submit(worker, "t2"),
                executor.submit(worker, "t3"),
            ]
            wait(futures)

        assert not errors, f"Errors occurred: {errors}"
        assert results["t1"] == "t1"
        assert results["t2"] == "t2"
        assert results["t3"] == "t3"

    def test_reset_clears_thread_local_fallback(self) -> None:
        """Reset properly deletes thread-local fallback attribute."""
        initial_token = _current_container.set(None)
        try:
            container = Container()
            token = container_context.set_current(container)

            # Verify fallback is set
            assert hasattr(_thread_local_fallback, "container")
            assert _thread_local_fallback.container is container

            # Reset should clear the fallback
            container_context.reset(token)

            # Verify fallback is cleared
            assert not hasattr(_thread_local_fallback, "container")
        finally:
            _current_container.reset(initial_token)

    def test_thread_local_fallback_used_when_contextvar_none(self) -> None:
        """Thread-local fallback returns container when ContextVar is None.

        This test covers line 259 in container_context.py where the thread-local
        fallback path is used when ContextVar returns None.
        """
        proxy = _ContainerContextProxy()
        container = Container()
        container.register(ServiceA, instance=ServiceA(id="thread-local-container"))

        # Store the original values to restore later
        original_default = proxy._default_container

        # First, set ContextVar to None explicitly
        token = _current_container.set(None)
        try:
            # Set thread-local directly (bypassing set_current to isolate the path)
            _thread_local_fallback.container = container

            # Clear class-level default to ensure we hit the thread-local path
            proxy._default_container = None

            # get_current should use thread-local fallback (line 259)
            result = proxy.get_current()
            assert result is container

            # Verify we can resolve from this container
            service = result.resolve(ServiceA)
            assert service.id == "thread-local-container"
        finally:
            # Clean up
            _current_container.reset(token)
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            proxy._default_container = original_default

    def test_thread_local_fallback_works_with_asyncio_run(self) -> None:
        """Thread-local fallback works when ContextVar is explicitly cleared."""
        # Set container in main thread
        container = Container()
        container.register(ServiceA, instance=ServiceA(id="main-thread"))

        token = container_context.set_current(container)
        try:
            # Note: asyncio.run() actually propagates ContextVar values to the coroutine.
            # To test the thread-local fallback, we explicitly clear the ContextVar
            # inside the async function.

            async def async_handler() -> str:
                # Clear the ContextVar to force fallback to thread-local storage
                inner_token = _current_container.set(None)
                try:
                    service = container_context.resolve(ServiceA)
                    return service.id
                finally:
                    _current_container.reset(inner_token)

            # This should work because the thread-local fallback is set
            result = asyncio.run(async_handler())
            assert result == "main-thread"
        finally:
            container_context.reset(token)

    def test_stress_multiple_threads_with_fallback(self) -> None:
        """Stress test with 50 threads using thread-local fallback."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        num_threads = 50
        results: dict[int, str] = {}
        errors: list[Exception] = []

        def worker(thread_num: int) -> tuple[int, str]:
            try:
                container = Container()
                container.register(ServiceA, instance=ServiceA(id=f"thread-{thread_num}"))

                token = container_context.set_current(container)
                try:
                    # Do multiple resolutions to increase chance of race conditions
                    for _ in range(10):
                        service = container_context.resolve(ServiceA)
                        if service.id != f"thread-{thread_num}":
                            msg = f"Thread {thread_num} saw wrong container: {service.id}"
                            raise AssertionError(msg)
                    return thread_num, container_context.resolve(ServiceA).id
                finally:
                    container_context.reset(token)
            except Exception as e:
                errors.append(e)
                raise

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            for future in as_completed(futures):
                # Errors are already captured in the errors list by the worker
                if not future.exception():
                    thread_num, result = future.result()
                    results[thread_num] = result

        assert not errors, f"Errors occurred: {errors}"
        assert len(results) == num_threads

        # Verify each thread saw its own container
        for i in range(num_threads):
            assert results[i] == f"thread-{i}", f"Thread {i} saw wrong value: {results[i]}"


# ============================================================================
# Integration with FastAPI-like Patterns
# ============================================================================


class TestFastAPILikeIntegration:
    """Tests for FastAPI-like integration patterns."""

    def test_decorator_before_app_startup(self) -> None:
        """Decorators can be applied at module load time before app startup."""
        initial_token = _current_container.set(None)
        try:
            # Simulate module-level decoration (before app startup)
            @container_context.resolve(scope="request")
            def get_data(
                name: str,
                service: Annotated[ServiceA, Injected()],
            ) -> dict[str, Any]:
                return {"name": name, "service_id": service.id}

            # Simulate app startup - set container
            container = Container()
            token = container_context.set_current(container)
            try:
                # Simulate request handling
                result = get_data("test")
                assert result["name"] == "test"
                assert isinstance(result["service_id"], str)
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)

    def test_multiple_endpoints_share_container(self) -> None:
        """Multiple endpoints decorated before container is set work correctly."""
        initial_token = _current_container.set(None)
        try:

            @container_context.resolve(scope="request")
            def endpoint1(service: Annotated[ServiceA, Injected()]) -> str:
                return f"endpoint1:{service.id}"

            @container_context.resolve(scope="request")
            def endpoint2(service: Annotated[ServiceA, Injected()]) -> str:
                return f"endpoint2:{service.id}"

            # Set up container
            container = Container()
            container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)
            token = container_context.set_current(container)
            try:
                result1 = endpoint1()
                result2 = endpoint2()

                # Each endpoint call creates its own scope, so different instances
                assert result1.startswith("endpoint1:")
                assert result2.startswith("endpoint2:")
                # Different scopes = different service instances
                id1 = result1.split(":")[1]
                id2 = result2.split(":")[1]
                assert id1 != id2
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)

    def test_generator_factory_cleanup_with_context(self) -> None:
        """Generator factory cleanup works through container_context."""
        cleanup_called = []

        def service_factory() -> Any:
            try:
                yield ServiceA(id="generated")
            finally:
                cleanup_called.append(True)

        container = Container()
        container.register(ServiceA, factory=service_factory, scope="request")

        token = container_context.set_current(container)
        try:

            @container_context.resolve(scope="request")
            def handler(service: Annotated[ServiceA, Injected()]) -> str:
                return service.id

            result = handler()
            assert result == "generated"
            assert cleanup_called == [True]
        finally:
            container_context.reset(token)


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_resolve_with_no_fromdi_params(self) -> None:
        """Function with no Injected params works."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve(scope="request")
            def handler(value: int) -> int:
                return value * 2

            result = handler(21)
            assert result == 42
        finally:
            container_context.reset(token)

    def test_resolve_with_defaults(self) -> None:
        """Non-injected parameters with defaults work."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                service: Annotated[ServiceA, Injected()],
                value: int = 10,
            ) -> tuple[int, ServiceA]:
                return value, service

            result1 = handler()
            assert result1[0] == 10
            assert isinstance(result1[1], ServiceA)

            result2 = handler(value=20)
            assert result2[0] == 20
        finally:
            container_context.reset(token)

    def test_resolve_with_args_kwargs(self) -> None:
        """*args and **kwargs work."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                *args: int,
                service: Annotated[ServiceA, Injected()],
                **kwargs: str,
            ) -> dict[str, Any]:
                return {"args": args, "kwargs": kwargs, "service": service}

            result = handler(1, 2, 3, name="test")
            assert result["args"] == (1, 2, 3)
            assert result["kwargs"] == {"name": "test"}
            assert isinstance(result["service"], ServiceA)
        finally:
            container_context.reset(token)

    def test_decorated_function_allows_explicit_kwargs_override(self) -> None:
        """Explicit kwargs can override injected dependencies."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                value: int,
                service: Annotated[ServiceA, Injected()],
            ) -> tuple[int, ServiceA]:
                return value, service

            custom_service = ServiceA(id="custom")
            result = handler(42, service=custom_service)

            assert result[0] == 42
            assert result[1].id == "custom"
        finally:
            container_context.reset(token)

    def test_nested_scopes_work_correctly(self) -> None:
        """Nested scopes through container_context work."""
        container = Container()
        container.register(ServiceA, scope="outer", lifetime=Lifetime.SCOPED)
        container.register(ServiceB, scope="inner", lifetime=Lifetime.SCOPED)

        token = container_context.set_current(container)
        try:
            with container_context.enter_scope("outer") as outer:
                service_a = container_context.resolve(ServiceA)
                assert isinstance(service_a, ServiceA)

                with outer.enter_scope("inner"):
                    service_b = container_context.resolve(ServiceB)
                    assert isinstance(service_b, ServiceB)

                    # ServiceA should still be resolvable in inner scope
                    service_a_inner = container_context.resolve(ServiceA)
                    assert service_a_inner is service_a
        finally:
            container_context.reset(token)

    def test_calling_handler_without_container_raises_error(self) -> None:
        """Calling decorated handler without container set raises DIWireContainerNotSetError."""
        initial_token = _current_container.set(None)
        try:

            @container_context.resolve()
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            with pytest.raises(DIWireContainerNotSetError):
                handler()
        finally:
            _current_container.reset(initial_token)

    def test_switching_containers_between_calls(self) -> None:
        """Container can be switched between calls to the same handler."""
        initial_token = _current_container.set(None)
        try:

            @container_context.resolve()
            def handler(service: Annotated[ServiceA, Injected()]) -> str:
                return service.id

            container1 = Container()
            container1.register(ServiceA, instance=ServiceA(id="first"))

            container2 = Container()
            container2.register(ServiceA, instance=ServiceA(id="second"))

            # First call with container1
            token1 = container_context.set_current(container1)
            result1 = handler()
            container_context.reset(token1)

            # Second call with container2
            token2 = container_context.set_current(container2)
            result2 = handler()
            container_context.reset(token2)

            assert result1 == "first"
            assert result2 == "second"
        finally:
            _current_container.reset(initial_token)


# ============================================================================
# Decorator Stacking Tests
# ============================================================================


class TestDecoratorStacking:
    """Tests for decorator stacking with other decorators."""

    def test_stacking_with_other_decorator_outer(self) -> None:
        """container_context.resolve works when stacked with other decorators (outer)."""
        container = Container()
        token = container_context.set_current(container)
        try:

            def logging_decorator(func: Any) -> Any:
                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    return func(*args, **kwargs)

                return wrapper

            @logging_decorator
            @container_context.resolve()
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            result = handler()
            assert isinstance(result, ServiceA)
        finally:
            container_context.reset(token)

    def test_stacking_with_functools_wraps_decorator_inner(self) -> None:
        """container_context.resolve works with functools.wraps decorator (inner)."""
        import functools

        container = Container()
        token = container_context.set_current(container)
        try:

            def logging_decorator(func: Any) -> Any:
                @functools.wraps(func)
                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    return func(*args, **kwargs)

                return wrapper

            @container_context.resolve()
            @logging_decorator
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            result = handler()
            assert isinstance(result, ServiceA)
        finally:
            container_context.reset(token)


# ============================================================================
# Error Propagation Tests
# ============================================================================


class TestErrorPropagation:
    """Tests for error handling and propagation."""

    def test_service_not_registered_error_propagates(self) -> None:
        """DIWireServiceNotRegisteredError propagates from decorated function."""
        from diwire.exceptions import DIWireServiceNotRegisteredError

        container = Container(autoregister=False)
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            with pytest.raises(DIWireServiceNotRegisteredError):
                handler()
        finally:
            container_context.reset(token)

    def test_circular_dependency_error_propagates(self) -> None:
        """DIWireCircularDependencyError propagates from decorated function."""
        from diwire.exceptions import DIWireCircularDependencyError

        # Use auto-registration (autoregister=True) for proper
        # circular dependency detection
        container = Container(autoregister=True)

        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(service: Annotated[_CircularA, Injected()]) -> _CircularA:
                return service

            with pytest.raises(DIWireCircularDependencyError):
                handler()
        finally:
            container_context.reset(token)

    def test_exception_in_handler_propagates(self) -> None:
        """Exceptions raised inside handler propagate correctly."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                raise ValueError("Handler error")

            with pytest.raises(ValueError, match="Handler error"):
                handler()
        finally:
            container_context.reset(token)

    @pytest.mark.asyncio
    async def test_async_exception_propagates(self) -> None:
        """Exceptions in async handler propagate correctly."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                raise ValueError("Async handler error")

            with pytest.raises(ValueError, match="Async handler error"):
                await handler()
        finally:
            container_context.reset(token)


# ============================================================================
# Multiple Injected Parameters Tests
# ============================================================================


class TestMultipleInjectedParameters:
    """Tests for functions with multiple Injected parameters."""

    def test_multiple_fromdi_params_same_type(self) -> None:
        """Function with multiple Injected params of same type."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                s1: Annotated[ServiceA, Injected()],
                s2: Annotated[ServiceA, Injected()],
            ) -> tuple[ServiceA, ServiceA]:
                return s1, s2

            result = handler()
            assert isinstance(result[0], ServiceA)
            assert isinstance(result[1], ServiceA)
            # (transient by default)
            # TRANSIENT means each parameter gets a fresh instance
            assert result[0] is not result[1]
        finally:
            container_context.reset(token)

    def test_multiple_fromdi_params_different_types(self) -> None:
        """Function with multiple Injected params of different types."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                a: Annotated[ServiceA, Injected()],
                b: Annotated[ServiceB, Injected()],
            ) -> tuple[ServiceA, ServiceB]:
                return a, b

            result = handler()
            assert isinstance(result[0], ServiceA)
            assert isinstance(result[1], ServiceB)
        finally:
            container_context.reset(token)

    def test_signature_hides_all_fromdi_params(self) -> None:
        """Signature hides all Injected parameters."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                value: int,
                a: Annotated[ServiceA, Injected()],
                name: str,
                b: Annotated[ServiceB, Injected()],
            ) -> dict[str, Any]:
                return {"value": value, "name": name, "a": a, "b": b}

            sig = inspect.signature(handler)
            param_names = list(sig.parameters.keys())
            assert param_names == ["value", "name"]
            assert "a" not in param_names
            assert "b" not in param_names
        finally:
            container_context.reset(token)


# ============================================================================
# Container Operations Without Container Tests
# ============================================================================


class TestContainerOperationsWithoutContainer:
    """Tests for proxy methods when no container is set."""

    def test_register_without_container_defers(self) -> None:
        """register() without container defers until set_current()."""
        initial_token = _current_container.set(None)
        try:
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            container_context._default_container = None
            container_context._deferred_registrations.clear()

            @container_context.register
            class DeferredService:
                pass

            container = Container(autoregister=False)
            token = container_context.set_current(container)
            try:
                service = container.resolve(DeferredService)
                assert isinstance(service, DeferredService)
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)
            container_context._deferred_registrations.clear()

    def test_enter_scope_without_container_raises_error(self) -> None:
        """enter_scope() without container raises DIWireContainerNotSetError."""
        initial_token = _current_container.set(None)
        try:
            with pytest.raises(DIWireContainerNotSetError):
                container_context.enter_scope("request")
        finally:
            _current_container.reset(initial_token)

    def test_compile_without_container_raises_error(self) -> None:
        """compile() without container raises DIWireContainerNotSetError."""
        initial_token = _current_container.set(None)
        try:
            with pytest.raises(DIWireContainerNotSetError):
                container_context.compile()
        finally:
            _current_container.reset(initial_token)

    @pytest.mark.asyncio
    async def test_aresolve_without_container_raises_error(self) -> None:
        """aresolve() without container raises DIWireContainerNotSetError."""
        initial_token = _current_container.set(None)
        try:
            with pytest.raises(DIWireContainerNotSetError):
                await container_context.aresolve(ServiceA)
        finally:
            _current_container.reset(initial_token)


# ============================================================================
# Deferred Registration Tests
# ============================================================================


class TestDeferredRegistrations:
    """Tests for deferred registration behavior."""

    def test_deferred_parameterized_decorator_registers_factory(self) -> None:
        """Parameterized decorator defers and registers on set_current()."""
        initial_token = _current_container.set(None)
        try:
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            container_context._default_container = None
            container_context._deferred_registrations.clear()

            @container_context.register(lifetime=Lifetime.SINGLETON)
            def create_service() -> ServiceA:
                return ServiceA(id="deferred-factory")

            container = Container(autoregister=False)
            token = container_context.set_current(container)
            try:
                service1 = container.resolve(ServiceA)
                service2 = container.resolve(ServiceA)
                assert service1 is service2
                assert service1.id == "deferred-factory"
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)
            container_context._deferred_registrations.clear()

    def test_parameterized_decorator_applies_after_container_set(self) -> None:
        """Decorator created before set_current applies when container is available."""
        initial_token = _current_container.set(None)
        try:
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            container_context._default_container = None
            container_context._deferred_registrations.clear()

            decorator = container_context.register(lifetime=Lifetime.SINGLETON)
            container = Container(autoregister=False)
            token = container_context.set_current(container)
            try:

                @decorator
                class LateService:
                    pass

                service = container.resolve(LateService)
                assert isinstance(service, LateService)
                assert not container_context._deferred_registrations
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)
            container_context._deferred_registrations.clear()

    def test_deferred_direct_call_registers_instance(self) -> None:
        """Direct call defers and registers instance on set_current()."""
        initial_token = _current_container.set(None)
        try:
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            container_context._default_container = None
            container_context._deferred_registrations.clear()

            instance = ServiceA(id="deferred-instance")
            container_context.register(ServiceA, instance=instance)

            container = Container(autoregister=False)
            token = container_context.set_current(container)
            try:
                assert container.resolve(ServiceA) is instance
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)
            container_context._deferred_registrations.clear()

    def test_register_uses_thread_local_fallback(self) -> None:
        """register() uses thread-local fallback when contextvar is None."""
        initial_token = _current_container.set(None)
        try:
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            container_context._default_container = None
            container_context._deferred_registrations.clear()

            container = Container(autoregister=False)
            _thread_local_fallback.container = container

            instance = ServiceA(id="thread-local")
            container_context.register(ServiceA, instance=instance)

            assert container.resolve(ServiceA) is instance
        finally:
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            container_context._default_container = None
            container_context._deferred_registrations.clear()
            _current_container.reset(initial_token)


# ============================================================================
# Async Repr Tests
# ============================================================================


class TestAsyncRepr:
    """Tests for async wrapper repr methods."""

    def test_async_context_injected_repr(self) -> None:
        """_AsyncContextInjected has informative repr."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            assert "_AsyncContextInjected" in repr(handler)
        finally:
            container_context.reset(token)

    def test_async_context_scoped_injected_repr(self) -> None:
        """_AsyncContextScopedInjected has informative repr."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve(scope="request")
            async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            assert "_AsyncContextScopedInjected" in repr(handler)
            assert "request" in repr(handler)
        finally:
            container_context.reset(token)


# ============================================================================
# Signature Edge Cases Tests
# ============================================================================


class TestSignatureEdgeCases:
    """Tests for signature edge cases."""

    def test_only_fromdi_params_results_in_empty_signature(self) -> None:
        """Function with only Injected params has empty signature."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                a: Annotated[ServiceA, Injected()],
                b: Annotated[ServiceB, Injected()],
            ) -> tuple[ServiceA, ServiceB]:
                return a, b

            sig = inspect.signature(handler)
            param_names = list(sig.parameters.keys())
            assert param_names == []
        finally:
            container_context.reset(token)

    def test_keyword_only_params_with_fromdi(self) -> None:
        """Keyword-only parameters with Injected work correctly."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                value: int,
                *,
                service: Annotated[ServiceA, Injected()],
                name: str = "default",
            ) -> dict[str, Any]:
                return {"value": value, "service": service, "name": name}

            sig = inspect.signature(handler)
            param_names = list(sig.parameters.keys())
            assert "value" in param_names
            assert "name" in param_names
            assert "service" not in param_names

            result = handler(42, name="test")
            assert result["value"] == 42
            assert result["name"] == "test"
            assert isinstance(result["service"], ServiceA)
        finally:
            container_context.reset(token)

    def test_positional_only_params_preserved(self) -> None:
        """Positional-only parameters are preserved in signature."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                value: int,
                /,
                service: Annotated[ServiceA, Injected()],
                name: str = "default",
            ) -> dict[str, Any]:
                return {"value": value, "service": service, "name": name}

            sig = inspect.signature(handler)
            params = sig.parameters
            assert "value" in params
            assert params["value"].kind == inspect.Parameter.POSITIONAL_ONLY
            assert "service" not in params

            result = handler(42)
            assert result["value"] == 42
            assert isinstance(result["service"], ServiceA)
        finally:
            container_context.reset(token)


# ============================================================================
# Method Decorator Tests
# ============================================================================


class TestMethodDecorators:
    """Tests for decorating methods."""

    def test_instance_method_decoration(self) -> None:
        """Instance methods can be decorated."""
        container = Container()
        token = container_context.set_current(container)
        try:

            class MyClass:
                @container_context.resolve()
                def handler(
                    self,
                    service: Annotated[ServiceA, Injected()],
                ) -> ServiceA:
                    return service

            obj = MyClass()
            result = obj.handler()
            assert isinstance(result, ServiceA)
        finally:
            container_context.reset(token)

    def test_static_method_decoration(self) -> None:
        """Static methods can be decorated."""
        container = Container()
        token = container_context.set_current(container)
        try:

            class MyClass:
                @staticmethod
                @container_context.resolve()
                def handler(
                    service: Annotated[ServiceA, Injected()],
                ) -> ServiceA:
                    return service

            result = MyClass.handler()
            assert isinstance(result, ServiceA)
        finally:
            container_context.reset(token)

    def test_class_method_decoration(self) -> None:
        """Class methods can be decorated."""
        container = Container()
        token = container_context.set_current(container)
        try:

            class MyClass:
                @classmethod
                @container_context.resolve()
                def handler(
                    cls,
                    service: Annotated[ServiceA, Injected()],
                ) -> tuple[type, ServiceA]:
                    return cls, service

            result_cls, result_service = MyClass.handler()
            assert result_cls is MyClass
            assert isinstance(result_service, ServiceA)
        finally:
            container_context.reset(token)


# ============================================================================
# Lifetime Variation Tests
# ============================================================================


class TestLifetimeVariations:
    """Tests for different lifetime configurations."""

    def test_transient_lifetime(self) -> None:
        """TRANSIENT lifetime creates new instance each resolution."""
        container = Container()
        container.register(ServiceA, lifetime=Lifetime.TRANSIENT)

        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                s1: Annotated[ServiceA, Injected()],
                s2: Annotated[ServiceA, Injected()],
            ) -> tuple[ServiceA, ServiceA]:
                return s1, s2

            result = handler()
            # TRANSIENT means different instances
            assert result[0].id != result[1].id
        finally:
            container_context.reset(token)

    def test_singleton_lifetime(self) -> None:
        """SINGLETON lifetime returns same instance."""
        container = Container()
        container.register(ServiceA, lifetime=Lifetime.SINGLETON)

        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            result1 = handler()
            result2 = handler()
            # SINGLETON means same instance
            assert result1.id == result2.id
        finally:
            container_context.reset(token)

    def test_scoped_same_scope(self) -> None:
        """SCOPED returns same instance within same scope."""
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)

        token = container_context.set_current(container)
        try:

            @container_context.resolve(scope="request")
            def handler(
                s1: Annotated[ServiceA, Injected()],
                s2: Annotated[ServiceA, Injected()],
            ) -> tuple[ServiceA, ServiceA]:
                return s1, s2

            result = handler()
            # Same scope means same instance
            assert result[0].id == result[1].id
        finally:
            container_context.reset(token)


# ============================================================================
# Async Generator Factory Tests
# ============================================================================


class TestAsyncGeneratorFactory:
    """Tests for async generator factories with container_context."""

    @pytest.mark.asyncio
    async def test_async_generator_factory_cleanup(self) -> None:
        """Async generator factory cleanup works through container_context."""
        cleanup_called = []

        async def async_service_factory() -> Any:
            try:
                yield ServiceA(id="async-generated")
            finally:
                cleanup_called.append(True)

        container = Container()
        container.register(ServiceA, factory=async_service_factory, scope="request")

        token = container_context.set_current(container)
        try:

            @container_context.resolve(scope="request")
            async def handler(service: Annotated[ServiceA, Injected()]) -> str:
                return service.id

            result = await handler()
            assert result == "async-generated"
            assert cleanup_called == [True]
        finally:
            container_context.reset(token)


# ============================================================================
# Service With Dependencies Tests
# ============================================================================


class TestServiceWithDependencies:
    """Tests for services that have dependencies on other services."""

    def test_resolve_service_with_dependency(self) -> None:
        """Resolving service with dependencies works."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                service: Annotated[ServiceWithDep, Injected()],
            ) -> ServiceWithDep:
                return service

            result = handler()
            assert isinstance(result, ServiceWithDep)
            assert isinstance(result.service_a, ServiceA)
        finally:
            container_context.reset(token)

    def test_resolve_service_with_registered_dependency(self) -> None:
        """Resolving service with pre-registered dependency works."""
        specific_a = ServiceA(id="specific-a")
        container = Container()
        container.register(ServiceA, instance=specific_a)

        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                service: Annotated[ServiceWithDep, Injected()],
            ) -> ServiceWithDep:
                return service

            result = handler()
            assert result.service_a.id == "specific-a"
        finally:
            container_context.reset(token)


# ============================================================================
# Return Value Edge Cases Tests
# ============================================================================


class TestReturnValueEdgeCases:
    """Tests for various return value scenarios."""

    def test_handler_returning_none(self) -> None:
        """Handler returning None works correctly."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(service: Annotated[ServiceA, Injected()]) -> None:
                _ = service

            result = handler()
            assert result is None
        finally:
            container_context.reset(token)

    def test_handler_returning_generator(self) -> None:
        """Handler returning a generator works correctly."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                service: Annotated[ServiceA, Injected()],
            ) -> Any:
                def gen() -> Any:
                    yield service.id
                    yield "done"

                return gen()

            result = handler()
            items = list(result)
            assert len(items) == 2
            assert items[1] == "done"
        finally:
            container_context.reset(token)

    @pytest.mark.asyncio
    async def test_async_handler_returning_async_generator(self) -> None:
        """Async handler returning async generator works correctly."""
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            async def handler(
                service: Annotated[ServiceA, Injected()],
            ) -> Any:
                async def agen() -> Any:
                    yield service.id
                    yield "done"

                return agen()

            result = await handler()
            items = []
            async for item in result:
                items.append(item)  # noqa: PERF401
            assert len(items) == 2
            assert items[1] == "done"
        finally:
            container_context.reset(token)


# ============================================================================
# Callable Objects Tests
# ============================================================================


class TestCallableObjects:
    """Tests for callable objects."""

    def test_callable_class_not_decorated_as_function(self) -> None:
        """Callable class instances are treated as types, not functions."""
        container = Container()
        token = container_context.set_current(container)
        try:

            class CallableService:
                def __call__(self) -> str:
                    return "called"

            # When passing a class, it should resolve the type, not wrap it
            result = container_context.resolve(CallableService)
            assert isinstance(result, CallableService)
            assert result() == "called"
        finally:
            container_context.reset(token)


# ============================================================================
# PEP 563 Compatibility Tests
# ============================================================================


class TestPEP563Compatibility:
    """Tests for PEP 563 (from __future__ import annotations) compatibility."""

    def test_string_annotations_work(self) -> None:
        """String annotations from PEP 563 work correctly."""
        # This file has `from __future__ import annotations` at the top
        # which means all annotations are strings at runtime
        container = Container()
        token = container_context.set_current(container)
        try:

            @container_context.resolve()
            def handler(
                service: Annotated[ServiceA, Injected()],
            ) -> ServiceA:
                return service

            # Should work despite string annotations
            result = handler()
            assert isinstance(result, ServiceA)

            # Signature should still work
            sig = inspect.signature(handler)
            assert "service" not in sig.parameters
        finally:
            container_context.reset(token)


# ============================================================================
# Token Handling Tests
# ============================================================================


class TestTokenHandling:
    """Tests for token handling edge cases."""

    def test_multiple_set_without_reset(self) -> None:
        """Multiple set_current calls without reset still work."""
        container1 = Container()
        container1.register(ServiceA, instance=ServiceA(id="c1"))

        container2 = Container()
        container2.register(ServiceA, instance=ServiceA(id="c2"))

        initial_token = _current_container.set(None)
        try:
            token1 = container_context.set_current(container1)
            assert container_context.resolve(ServiceA).id == "c1"

            # Set again without reset
            token2 = container_context.set_current(container2)
            assert container_context.resolve(ServiceA).id == "c2"

            # Reset to container1
            container_context.reset(token2)
            assert container_context.resolve(ServiceA).id == "c1"

            container_context.reset(token1)
        finally:
            _current_container.reset(initial_token)

    def test_nested_container_contexts(self) -> None:
        """Nested container contexts work correctly."""
        outer_container = Container()
        outer_container.register(ServiceA, instance=ServiceA(id="outer"))

        inner_container = Container()
        inner_container.register(ServiceA, instance=ServiceA(id="inner"))

        initial_token = _current_container.set(None)
        try:
            outer_token = container_context.set_current(outer_container)
            assert container_context.resolve(ServiceA).id == "outer"

            inner_token = container_context.set_current(inner_container)
            assert container_context.resolve(ServiceA).id == "inner"

            container_context.reset(inner_token)
            assert container_context.resolve(ServiceA).id == "outer"

            container_context.reset(outer_token)
        finally:
            _current_container.reset(initial_token)


# ============================================================================
# Direct Function Resolution Tests
# ============================================================================


class TestDirectFunctionResolution:
    """Tests for direct function resolution without decorator syntax."""

    def test_resolve_function_directly_sync(self) -> None:
        """Directly resolving a function works."""
        container = Container()
        token = container_context.set_current(container)
        try:

            def my_handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            wrapped = container_context.resolve(my_handler)
            result = wrapped()
            assert isinstance(result, ServiceA)
        finally:
            container_context.reset(token)

    @pytest.mark.asyncio
    async def test_resolve_function_directly_async(self) -> None:
        """Directly resolving an async function works."""
        container = Container()
        token = container_context.set_current(container)
        try:

            async def my_handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            wrapped = container_context.resolve(my_handler)
            result = await wrapped()
            assert isinstance(result, ServiceA)
        finally:
            container_context.reset(token)


# ============================================================================
# Overload Behavior Tests
# ============================================================================


class TestOverloadBehavior:
    """Tests for different resolve() overload behaviors."""

    def test_resolve_with_none_returns_decorator(self) -> None:
        """resolve(None) returns a decorator."""
        container = Container()
        token = container_context.set_current(container)
        try:
            decorator = container_context.resolve(None)
            assert callable(decorator)

            @decorator
            def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            assert isinstance(handler, _ContextInjected)
        finally:
            container_context.reset(token)

    def test_resolve_empty_call_returns_decorator(self) -> None:
        """resolve() with no args returns a decorator."""
        container = Container()
        token = container_context.set_current(container)
        try:
            decorator = container_context.resolve()
            assert callable(decorator)
        finally:
            container_context.reset(token)

    def test_resolve_type_returns_instance(self) -> None:
        """resolve(Type) returns an instance."""
        container = Container()
        token = container_context.set_current(container)
        try:
            result = container_context.resolve(ServiceA)
            assert isinstance(result, ServiceA)
        finally:
            container_context.reset(token)

    def test_resolve_function_returns_wrapper(self) -> None:
        """resolve(function) returns a wrapper."""
        container = Container()
        token = container_context.set_current(container)
        try:

            def my_func(service: Annotated[ServiceA, Injected()]) -> ServiceA:
                return service

            result = container_context.resolve(my_func)
            assert isinstance(result, _ContextInjected)
        finally:
            container_context.reset(token)


# ============================================================================
# Context Injected Descriptor Tests
# ============================================================================


class TestContextInjectedDescriptors:
    """Tests for context injected descriptor __get__ methods."""

    def test_context_injected_get_returns_self_when_obj_none(self) -> None:
        """_ContextInjected descriptor returns self when accessed on class."""

        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        proxy = _ContainerContextProxy()
        context_injected = _ContextInjected(handler, proxy)

        # When obj is None, __get__ should return self
        result = context_injected.__get__(None, type(context_injected))
        assert result is context_injected

    def test_context_scoped_injected_get_returns_self_when_obj_none(self) -> None:
        """_ContextScopedInjected descriptor returns self when accessed on class."""

        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        proxy = _ContainerContextProxy()
        context_scoped_injected = _ContextScopedInjected(handler, proxy, "request")

        # When obj is None, __get__ should return self
        result = context_scoped_injected.__get__(None, type(context_scoped_injected))
        assert result is context_scoped_injected

    def test_context_scoped_injected_get_returns_method_when_obj_not_none(self) -> None:
        """_ContextScopedInjected descriptor returns MethodType when accessed on instance."""
        import types

        def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        proxy = _ContainerContextProxy()
        context_scoped_injected = _ContextScopedInjected(handler, proxy, "request")

        # When obj is not None, __get__ should return MethodType bound to obj
        dummy_obj = object()
        result = context_scoped_injected.__get__(dummy_obj, type(dummy_obj))
        assert isinstance(result, types.MethodType)

    def test_async_context_injected_get_returns_self_when_obj_none(self) -> None:
        """_AsyncContextInjected descriptor returns self when accessed on class."""

        async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        proxy = _ContainerContextProxy()
        async_context_injected = _AsyncContextInjected(handler, proxy)

        # When obj is None, __get__ should return self
        result = async_context_injected.__get__(None, type(async_context_injected))
        assert result is async_context_injected

    def test_async_context_injected_get_returns_method_when_obj_not_none(self) -> None:
        """_AsyncContextInjected descriptor returns MethodType when accessed on instance."""
        import types

        async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        proxy = _ContainerContextProxy()
        async_context_injected = _AsyncContextInjected(handler, proxy)

        # When obj is not None, __get__ should return MethodType bound to obj
        dummy_obj = object()
        result = async_context_injected.__get__(dummy_obj, type(dummy_obj))
        assert isinstance(result, types.MethodType)

    def test_async_context_scoped_injected_get_returns_self_when_obj_none(self) -> None:
        """_AsyncContextScopedInjected descriptor returns self when accessed on class."""

        async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        proxy = _ContainerContextProxy()
        async_context_scoped_injected = _AsyncContextScopedInjected(handler, proxy, "request")

        # When obj is None, __get__ should return self
        result = async_context_scoped_injected.__get__(None, type(async_context_scoped_injected))
        assert result is async_context_scoped_injected

    def test_async_context_scoped_injected_get_returns_method_when_obj_not_none(self) -> None:
        """_AsyncContextScopedInjected descriptor returns MethodType when accessed on instance."""
        import types

        async def handler(service: Annotated[ServiceA, Injected()]) -> ServiceA:
            return service

        proxy = _ContainerContextProxy()
        async_context_scoped_injected = _AsyncContextScopedInjected(handler, proxy, "request")

        # When obj is not None, __get__ should return MethodType bound to obj
        dummy_obj = object()
        result = async_context_scoped_injected.__get__(dummy_obj, type(dummy_obj))
        assert isinstance(result, types.MethodType)


# ============================================================================
# Cross-Thread Default Container Tests
# ============================================================================


class TestCrossThreadDefaultContainer:
    """Tests for cross-thread default container access.

    These tests verify that set_current() also sets a class-level default
    container that can be accessed from thread pool workers (e.g., FastAPI
    sync endpoint handlers).
    """

    def test_default_container_accessible_from_different_thread(self) -> None:
        """Container set in main thread is accessible from worker thread."""
        from concurrent.futures import ThreadPoolExecutor

        container = Container()
        container.register(ServiceA, instance=ServiceA(id="main-thread-container"))

        results: dict[str, str | None] = {}
        errors: list[Exception] = []

        def worker() -> None:
            try:
                # Worker thread should see the container set in main thread
                # via the class-level default (not ContextVar or thread-local)
                service = container_context.resolve(ServiceA)
                results["worker"] = service.id
            except Exception as e:
                errors.append(e)

        token = container_context.set_current(container)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(worker)
                future.result()

            assert not errors, f"Errors occurred: {errors}"
            assert results["worker"] == "main-thread-container"
        finally:
            container_context.reset(token)

    def test_default_container_accessible_from_multiple_threads(self) -> None:
        """Container is accessible from multiple concurrent worker threads."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        container = Container()
        container.register(ServiceA, instance=ServiceA(id="shared-container"))

        results: dict[int, str] = {}
        errors: list[Exception] = []

        def worker(thread_num: int) -> tuple[int, str]:
            try:
                service = container_context.resolve(ServiceA)
            except Exception as e:
                errors.append(e)
                raise
            else:
                return thread_num, service.id

        token = container_context.set_current(container)
        try:
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(worker, i) for i in range(10)]
                for future in as_completed(futures):
                    if not future.exception():
                        thread_num, result = future.result()
                        results[thread_num] = result

            assert not errors, f"Errors occurred: {errors}"
            assert len(results) == 10
            for i in range(10):
                assert results[i] == "shared-container"
        finally:
            container_context.reset(token)

    def test_reset_clears_default_container(self) -> None:
        """reset() clears the class-level default container."""
        from concurrent.futures import ThreadPoolExecutor

        container = Container()
        initial_token = _current_container.set(None)
        try:
            token = container_context.set_current(container)

            # Verify default is set
            assert container_context._default_container is container

            # Reset should clear the default
            container_context.reset(token)

            # Default should now be None
            # Cast to Any to break mypy's type narrowing from the previous assertion
            proxy: Any = container_context
            assert proxy._default_container is None

            # Worker thread should not see any container
            errors: list[Exception] = []

            def worker() -> None:
                try:
                    container_context.resolve(ServiceA)
                except DIWireContainerNotSetError:
                    pass  # Expected
                except Exception as e:
                    errors.append(e)

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(worker)
                future.result()

            assert not errors
        finally:
            _current_container.reset(initial_token)

    def test_default_container_fallback_when_contextvar_and_threadlocal_cleared(self) -> None:
        """get_current() falls back to _default_container when ContextVar and thread-local are unset."""
        container = Container()
        container.register(ServiceA, instance=ServiceA(id="default-fallback"))

        initial_token = _current_container.set(None)
        original_default = container_context._default_container
        had_thread_local = hasattr(_thread_local_fallback, "container")
        original_thread_local = getattr(_thread_local_fallback, "container", None)
        try:
            # Set _default_container but clear ContextVar and thread-local
            container_context._default_container = container
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container

            # get_current should fall through to _default_container (line 320)
            result = container_context.get_current()
            assert result is container
        finally:
            _current_container.reset(initial_token)
            container_context._default_container = original_default
            if had_thread_local:
                _thread_local_fallback.container = original_thread_local
            elif hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container

    def test_decorated_sync_handler_works_from_thread_pool(self) -> None:
        """Decorated sync handlers work when called from thread pool."""
        from concurrent.futures import ThreadPoolExecutor

        container = Container()
        container.register(ServiceA, instance=ServiceA(id="thread-pool-test"))

        @container_context.resolve(scope="request")
        def handler(
            value: int,
            service: Annotated[ServiceA, Injected()],
        ) -> dict[str, Any]:
            return {"value": value, "service_id": service.id}

        results: dict[str, Any] = {}
        errors: list[Exception] = []

        def worker() -> None:
            try:
                result = handler(42)
                results["handler_result"] = result
            except Exception as e:
                errors.append(e)

        token = container_context.set_current(container)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(worker)
                future.result()

            assert not errors, f"Errors occurred: {errors}"
            assert results["handler_result"]["value"] == 42
            assert results["handler_result"]["service_id"] == "thread-pool-test"
        finally:
            container_context.reset(token)

    def test_instance_method_works_from_thread_pool(self) -> None:
        """Decorated instance methods work when called from thread pool."""
        from concurrent.futures import ThreadPoolExecutor

        container = Container()
        container.register(ServiceA, instance=ServiceA(id="instance-method-test"))

        class Handler:
            @container_context.resolve(scope="request")
            def handle(
                self,
                name: str,
                service: Annotated[ServiceA, Injected()],
            ) -> dict[str, str]:
                return {"name": name, "service_id": service.id}

        handler_instance = Handler()
        results: dict[str, Any] = {}
        errors: list[Exception] = []

        def worker() -> None:
            try:
                result = handler_instance.handle("test")
                results["handler_result"] = result
            except Exception as e:
                errors.append(e)

        token = container_context.set_current(container)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(worker)
                future.result()

            assert not errors, f"Errors occurred: {errors}"
            assert results["handler_result"]["name"] == "test"
            assert results["handler_result"]["service_id"] == "instance-method-test"
        finally:
            container_context.reset(token)


# ============================================================================
# Deferred Registration with Type Key Tests
# ============================================================================


class TestDeferredRegistrationWithTypeKey:
    """Tests for deferred registration when using a type as key without container."""

    def test_deferred_factory_with_type_key(self) -> None:
        """Deferred factory registration with type key works when container is set later."""
        initial_token = _current_container.set(None)
        try:
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            container_context._default_container = None
            container_context._deferred_registrations.clear()

            # Register factory with type key and non-default params (deferred)
            # Use ServiceA which is defined at module level
            @container_context.register(ServiceA, lifetime=Lifetime.SINGLETON)  # type: ignore[misc, untyped-decorator]
            def create_service() -> ServiceA:
                return ServiceA(id="deferred-factory-value")

            # Verify function was returned
            assert callable(create_service)

            container = Container(autoregister=False)
            token = container_context.set_current(container)
            try:
                service = container.resolve(ServiceA)
                assert service.id == "deferred-factory-value"
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)
            container_context._deferred_registrations.clear()

    def test_deferred_interface_registration_with_type_key(self) -> None:
        """Deferred interface registration with type key works when container is set later."""
        initial_token = _current_container.set(None)
        try:
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            container_context._default_container = None
            container_context._deferred_registrations.clear()

            class IDatabase:
                pass

            class PostgresDB(IDatabase):
                pass

            # Register with interface key and non-default params (deferred)
            @cast("Any", container_context.register(IDatabase, lifetime=Lifetime.SINGLETON))
            class PostgresDBImpl(IDatabase):  # type: ignore[misc]
                pass

            container = Container(autoregister=False)
            token = container_context.set_current(container)
            try:
                db = container.resolve(IDatabase)
                assert isinstance(db, PostgresDBImpl)
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)
            container_context._deferred_registrations.clear()

    def test_type_key_with_container_set_delegates_to_container(self) -> None:
        """When container is set, type key registration delegates to container."""
        container = Container()
        token = container_context.set_current(container)
        try:
            container_context._deferred_registrations.clear()

            class IRepository:
                pass

            @container_context.register(IRepository)
            class SqlRepository(IRepository):  # type: ignore[call-arg]
                pass

            # Should be registered directly, not deferred
            assert not container_context._deferred_registrations

            repo = container.resolve(IRepository)
            assert isinstance(repo, SqlRepository)
        finally:
            container_context.reset(token)

    def test_type_decorator_applied_after_container_set(self) -> None:
        """Type decorator applies when container becomes available between creation and use."""
        initial_token = _current_container.set(None)
        try:
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            container_context._default_container = None
            container_context._deferred_registrations.clear()

            class MyInterface:
                pass

            # Create decorator without container
            decorator = container_context.register(MyInterface, lifetime=Lifetime.SINGLETON)

            # Set container
            container = Container(autoregister=False)
            token = container_context.set_current(container)
            try:
                # Apply decorator - should delegate to container
                @cast("Any", decorator)
                class MyImpl(MyInterface):  # type: ignore[misc]
                    pass

                instance = container.resolve(MyInterface)
                assert isinstance(instance, MyImpl)
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)
            container_context._deferred_registrations.clear()

    def test_staticmethod_deferred_registration(self) -> None:
        """Staticmethod decorator defers when no container is set."""
        initial_token = _current_container.set(None)
        try:
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            container_context._default_container = None
            container_context._deferred_registrations.clear()

            @staticmethod  # type: ignore[misc]
            @container_context.register
            def create_service() -> ServiceA:
                return ServiceA(id="staticmethod-deferred")

            # Should have deferred registration
            assert len(container_context._deferred_registrations) == 1

            container = Container(autoregister=False)
            token = container_context.set_current(container)
            try:
                service = container.resolve(ServiceA)
                assert service.id == "staticmethod-deferred"
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)
            container_context._deferred_registrations.clear()

    def test_type_decorator_on_same_type_deferred(self) -> None:
        """Type decorator applied to same type defers correctly."""
        initial_token = _current_container.set(None)
        try:
            if hasattr(_thread_local_fallback, "container"):
                del _thread_local_fallback.container
            container_context._default_container = None
            container_context._deferred_registrations.clear()

            class MyConfig:
                pass

            # Get decorator with non-default params without container
            decorator = container_context.register(MyConfig, lifetime=Lifetime.SINGLETON)

            # Apply to the SAME class (edge case: target is interface_key)
            result = decorator(MyConfig)  # type: ignore[misc]

            # Should return the original class
            assert result is MyConfig

            # Should have deferred registration
            assert len(container_context._deferred_registrations) == 1

            container = Container(autoregister=False)
            token = container_context.set_current(container)
            try:
                config = container.resolve(MyConfig)
                assert isinstance(config, MyConfig)
            finally:
                container_context.reset(token)
        finally:
            _current_container.reset(initial_token)
            container_context._deferred_registrations.clear()


# ============================================================================
# Close/AClose Method Tests
# ============================================================================


class TestContainerContextClose:
    """Tests for close/aclose methods on _ContainerContextProxy."""

    def test_close_delegates_to_current_container(self) -> None:
        """close() delegates to the current container's close method."""
        proxy = _ContainerContextProxy()
        container = Container()
        token = proxy.set_current(container)
        try:
            proxy.close()
            assert container._closed
        finally:
            proxy.reset(token)

    async def test_aclose_delegates_to_current_container(self) -> None:
        """aclose() delegates to the current container's aclose method."""
        proxy = _ContainerContextProxy()
        container = Container()
        token = proxy.set_current(container)
        try:
            await proxy.aclose()
            assert container._closed
        finally:
            proxy.reset(token)

    def test_close_without_container_raises_error(self) -> None:
        """close() raises DIWireContainerNotSetError when no container set."""
        proxy = _ContainerContextProxy()
        token = _current_container.set(None)
        try:
            with pytest.raises(DIWireContainerNotSetError):
                proxy.close()
        finally:
            _current_container.reset(token)

    async def test_aclose_without_container_raises_error(self) -> None:
        """aclose() raises DIWireContainerNotSetError when no container set."""
        proxy = _ContainerContextProxy()
        token = _current_container.set(None)
        try:
            with pytest.raises(DIWireContainerNotSetError):
                await proxy.aclose()
        finally:
            _current_container.reset(token)

    def test_close_scope_delegates_to_current_container(self) -> None:
        """close_scope() delegates to the current container's close_scope method."""
        proxy = _ContainerContextProxy()
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)
        token = proxy.set_current(container)
        try:
            scope = proxy.enter_scope("request")
            proxy.resolve(ServiceA)
            assert not scope._exited

            proxy.close_scope("request")
            assert scope._exited
        finally:
            proxy.reset(token)

    async def test_aclose_scope_delegates_to_current_container(self) -> None:
        """aclose_scope() delegates to the current container's aclose_scope method."""
        proxy = _ContainerContextProxy()
        container = Container()
        container.register(ServiceA, scope="request", lifetime=Lifetime.SCOPED)
        token = proxy.set_current(container)
        try:
            scope = proxy.enter_scope("request")
            await proxy.aresolve(ServiceA)
            assert not scope._exited

            await proxy.aclose_scope("request")
            assert scope._exited
        finally:
            proxy.reset(token)

    def test_close_scope_without_container_raises_error(self) -> None:
        """close_scope() raises DIWireContainerNotSetError when no container set."""
        proxy = _ContainerContextProxy()
        token = _current_container.set(None)
        try:
            with pytest.raises(DIWireContainerNotSetError):
                proxy.close_scope("request")
        finally:
            _current_container.reset(token)

    async def test_aclose_scope_without_container_raises_error(self) -> None:
        """aclose_scope() raises DIWireContainerNotSetError when no container set."""
        proxy = _ContainerContextProxy()
        token = _current_container.set(None)
        try:
            with pytest.raises(DIWireContainerNotSetError):
                await proxy.aclose_scope("request")
        finally:
            _current_container.reset(token)
