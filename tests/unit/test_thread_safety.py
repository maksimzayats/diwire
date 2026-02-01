"""Tests for thread safety of Container."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from diwire.container import Container
from diwire.exceptions import DIWireCircularDependencyError
from diwire.types import Lifetime


class ServiceA:
    pass


class ServiceB:
    def __init__(self, a: ServiceA) -> None:
        self.a = a


class SlowAsyncService:
    """Service used for testing async singleton double-check locking."""

    _creation_count: int = 0

    def __init__(self) -> None:
        SlowAsyncService._creation_count += 1

    @classmethod
    def reset_count(cls) -> None:
        cls._creation_count = 0

    @classmethod
    def get_count(cls) -> int:
        return cls._creation_count


async def slow_async_service_factory() -> SlowAsyncService:
    """Factory that introduces a delay to simulate slow async resolution."""
    await asyncio.sleep(0.05)
    return SlowAsyncService()


class TestConcurrentResolution:
    def test_concurrent_singleton_resolution_same_instance(
        self,
        container_singleton: Container,
    ) -> None:
        """Concurrent singleton resolution returns same instance."""
        results: list[ServiceA] = []
        errors: list[Exception] = []

        def resolve_service() -> None:
            try:
                instance = container_singleton.resolve(ServiceA)
                results.append(instance)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=resolve_service) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 10
        # All should be the same instance
        assert all(r is results[0] for r in results)

    def test_concurrent_transient_resolution_different_instances(
        self,
        container: Container,
    ) -> None:
        """Concurrent transient resolution creates different instances."""
        results: list[ServiceA] = []
        errors: list[Exception] = []

        def resolve_service() -> None:
            try:
                instance = container.resolve(ServiceA)
                results.append(instance)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=resolve_service) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 10
        # All should be different instances
        unique_instances = {id(r) for r in results}
        assert len(unique_instances) == 10


class TestConcurrentRegistration:
    def test_concurrent_registration_no_corruption(self) -> None:
        """Concurrent registration doesn't corrupt registry."""
        container = Container(autoregister=False)
        errors: list[Exception] = []

        def register_service(i: int) -> None:
            try:

                class DynamicService:
                    index = i

                container.register(DynamicService)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_service, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    def test_concurrent_registration_and_resolution(self) -> None:
        """Concurrent registration and resolution don't deadlock."""
        container = Container(autoregister=True)
        results: list[object] = []
        errors: list[Exception] = []

        def register_and_resolve() -> None:
            try:

                class LocalService:
                    pass

                container.register(LocalService)
                instance = container.resolve(LocalService)
                results.append(instance)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_and_resolve) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 10


class TestRaceConditions:
    def test_singleton_double_creation_race_condition(self) -> None:
        """Test that singleton creation creates only one instance under race conditions.

        With proper double-check locking, only a single instance should be created
        even when many threads race to resolve the same singleton.
        """
        container = Container(
            autoregister=True,
            autoregister_default_lifetime=Lifetime.SINGLETON,
        )

        class SlowInit:
            instance_count = 0

            def __init__(self) -> None:
                SlowInit.instance_count += 1

        results: list[SlowInit] = []

        def resolve_slow() -> None:
            instance = container.resolve(SlowInit)
            results.append(instance)

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(resolve_slow) for _ in range(20)]
            for f in as_completed(futures):
                f.result()  # Raise any exceptions

        # All results should be the same instance
        assert len(results) == 20
        # Only one instance should have been created
        assert SlowInit.instance_count == 1
        # All resolved instances should be the same object
        assert all(r is results[0] for r in results)


class TestStress:
    def test_many_concurrent_resolutions(self) -> None:
        """100 threads resolving concurrently."""
        container = Container(autoregister=True)

        class StressService:
            def __init__(self, a: ServiceA, b: ServiceB) -> None:
                self.a = a
                self.b = b

        results: list[StressService] = []
        errors: list[Exception] = []

        def resolve_complex() -> None:
            try:
                instance = container.resolve(StressService)
                results.append(instance)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=resolve_complex) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 100
        # All instances should have proper dependencies
        for r in results:
            assert isinstance(r.a, ServiceA)
            assert isinstance(r.b, ServiceB)
            assert isinstance(r.b.a, ServiceA)


# Circular dependency classes for thread safety tests
class CircularX:
    """X -> Y (circular)."""

    def __init__(self, y: "CircularY") -> None:
        self.y = y


class CircularY:
    """Y -> X (circular)."""

    def __init__(self, x: "CircularX") -> None:
        self.x = x


class TestCircularDetectionThreadSafety:
    def test_circular_detection_thread_isolated(self) -> None:
        """Each thread has its own resolution stack."""
        container = Container(autoregister=True)
        circular_errors: list[DIWireCircularDependencyError] = []
        unexpected_errors: list[Exception] = []

        def resolve_circular() -> None:
            try:
                container.resolve(CircularX)
            except DIWireCircularDependencyError as e:
                circular_errors.append(e)  # Expected
            except Exception as e:
                unexpected_errors.append(e)  # Unexpected error

        threads = [threading.Thread(target=resolve_circular) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have no unexpected errors (only DIWireCircularDependencyError)
        assert not unexpected_errors
        # Each thread should have detected the circular dependency
        assert len(circular_errors) == 10

    def test_concurrent_circular_and_normal_resolution(self) -> None:
        """Circular detection in one thread doesn't affect normal resolution in another."""
        container = Container(autoregister=True)
        normal_results: list[ServiceA] = []
        circular_errors: list[DIWireCircularDependencyError] = []
        unexpected_errors: list[Exception] = []

        def resolve_normal() -> None:
            try:
                instance = container.resolve(ServiceA)
                normal_results.append(instance)
            except Exception as e:
                unexpected_errors.append(e)

        def resolve_circular() -> None:
            try:
                container.resolve(CircularX)
            except DIWireCircularDependencyError as e:
                circular_errors.append(e)
            except Exception as e:
                unexpected_errors.append(e)

        # Mix normal and circular resolutions
        threads = []
        for i in range(20):
            if i % 2 == 0:
                threads.append(threading.Thread(target=resolve_normal))
            else:
                threads.append(threading.Thread(target=resolve_circular))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not unexpected_errors
        assert len(normal_results) == 10
        assert len(circular_errors) == 10


# Circular dependency classes for async tests
class AsyncCircularA:
    """A -> B (circular)."""

    def __init__(self, b: "AsyncCircularB") -> None:
        self.b = b


class AsyncCircularB:
    """B -> A (circular)."""

    def __init__(self, a: "AsyncCircularA") -> None:
        self.a = a


class TestAsyncContextIsolation:
    def test_circular_detection_async_task_isolated(self) -> None:
        """Each async task has its own resolution stack."""
        container = Container(autoregister=True)
        circular_errors: list[DIWireCircularDependencyError] = []
        unexpected_errors: list[Exception] = []

        async def resolve_circular() -> None:
            try:
                container.resolve(AsyncCircularA)
            except DIWireCircularDependencyError as e:
                circular_errors.append(e)
            except Exception as e:
                unexpected_errors.append(e)

        async def run_test() -> None:
            # Run multiple async tasks concurrently
            await asyncio.gather(*[resolve_circular() for _ in range(10)])

        asyncio.run(run_test())

        assert not unexpected_errors
        assert len(circular_errors) == 10

    def test_concurrent_async_circular_and_normal_resolution(self) -> None:
        """Circular detection in one async task doesn't affect normal resolution in another."""
        container = Container(autoregister=True)
        normal_results: list[ServiceA] = []
        circular_errors: list[DIWireCircularDependencyError] = []
        unexpected_errors: list[Exception] = []

        async def resolve_normal() -> None:
            try:
                instance = container.resolve(ServiceA)
                normal_results.append(instance)
            except Exception as e:
                unexpected_errors.append(e)

        async def resolve_circular() -> None:
            try:
                container.resolve(AsyncCircularA)
            except DIWireCircularDependencyError as e:
                circular_errors.append(e)
            except Exception as e:
                unexpected_errors.append(e)

        async def run_test() -> None:
            # Mix normal and circular resolutions
            tasks = []
            for i in range(20):
                if i % 2 == 0:
                    tasks.append(resolve_normal())
                else:
                    tasks.append(resolve_circular())

            await asyncio.gather(*tasks)

        asyncio.run(run_test())

        assert not unexpected_errors
        assert len(normal_results) == 10
        assert len(circular_errors) == 10

    def test_async_normal_resolution_works(self) -> None:
        """Normal resolution works correctly in async context."""
        container = Container(autoregister=True)
        results: list[ServiceB] = []

        async def resolve_service() -> None:
            instance = container.resolve(ServiceB)
            results.append(instance)

        async def run_test() -> None:
            await asyncio.gather(*[resolve_service() for _ in range(10)])

        asyncio.run(run_test())

        assert len(results) == 10
        for r in results:
            assert isinstance(r, ServiceB)
            assert isinstance(r.a, ServiceA)


class TestAsyncConcurrentResolution:
    """Tests for concurrent async resolution."""

    async def test_concurrent_async_singleton_returns_same_instance(self) -> None:
        """Concurrent async singleton resolution returns same instance."""
        container = Container(
            autoregister=True,
            autoregister_default_lifetime=Lifetime.SINGLETON,
        )
        results: list[ServiceA] = []

        async def worker() -> None:
            instance = await container.aresolve(ServiceA)
            results.append(instance)

        await asyncio.gather(*[worker() for _ in range(10)])

        assert len(results) == 10
        # All should be the same instance
        assert all(r is results[0] for r in results)

    async def test_concurrent_async_transient_returns_different_instances(self) -> None:
        """Concurrent async transient resolution returns different instances."""
        container = Container(autoregister=True)
        results: list[ServiceA] = []

        async def worker() -> None:
            instance = await container.aresolve(ServiceA)
            results.append(instance)

        await asyncio.gather(*[worker() for _ in range(10)])

        assert len(results) == 10
        # All should be different instances
        unique_ids = {id(r) for r in results}
        assert len(unique_ids) == 10

    async def test_async_resolution_with_dependencies(self) -> None:
        """Concurrent async resolution with dependencies works correctly."""
        container = Container(autoregister=True)
        results: list[ServiceB] = []

        async def worker() -> None:
            instance = await container.aresolve(ServiceB)
            results.append(instance)

        await asyncio.gather(*[worker() for _ in range(10)])

        assert len(results) == 10
        for r in results:
            assert isinstance(r, ServiceB)
            assert isinstance(r.a, ServiceA)

    async def test_async_singleton_double_check_locking(self) -> None:
        """Test that double-check locking works correctly for async singletons.

        This test ensures multiple concurrent coroutines resolving the same
        singleton all get the same instance due to double-check locking.
        """
        # Use a simple class that's already defined (ServiceA) with singleton lifetime
        container = Container(
            autoregister=True,
            autoregister_default_lifetime=Lifetime.SINGLETON,
            auto_compile=False,  # Disable compilation to use aresolve path
        )

        # Use an Event to synchronize workers starting together
        start_event = asyncio.Event()
        results: list[ServiceA] = []

        async def worker() -> None:
            await start_event.wait()  # All workers start together
            instance = await container.aresolve(ServiceA)
            results.append(instance)

        # Create all worker tasks
        tasks = [asyncio.create_task(worker()) for _ in range(20)]
        # Give tasks time to start and wait on the event
        await asyncio.sleep(0.01)
        # Release all workers simultaneously
        start_event.set()
        # Wait for all to complete
        await asyncio.gather(*tasks)

        assert len(results) == 20
        # All should be the same instance
        assert all(r is results[0] for r in results)

    async def test_async_singleton_with_slow_factory_double_check(self) -> None:
        """Test double-check locking with a slow async factory.

        This test directly exercises the double-check path by:
        1. Starting a singleton resolution that acquires the lock
        2. While holding the lock, manually populating the singleton cache
        3. Verifying the cached value is returned
        """
        from diwire.service_key import ServiceKey

        SlowAsyncService.reset_count()

        container = Container(autoregister=False, auto_compile=False)
        container.register(
            SlowAsyncService,
            factory=slow_async_service_factory,
            lifetime=Lifetime.SINGLETON,
        )

        service_key = ServiceKey.from_value(SlowAsyncService)

        # Get the singleton lock
        singleton_lock = await container._locks.get_singleton_lock(service_key)

        # Create a pre-made instance to inject into the cache
        injected_instance = SlowAsyncService()

        # Hold the lock while we populate the cache
        async with singleton_lock:
            # Populate the singleton cache while holding the lock
            container._singletons[service_key] = injected_instance

        # Reset count to verify the factory wasn't called
        initial_count = SlowAsyncService.get_count()

        # Now resolve - should hit the double-check path and return cached instance
        result = await container.aresolve(SlowAsyncService)

        # Should be the same instance we injected
        assert result is injected_instance
        # Factory should not have been called again
        assert SlowAsyncService.get_count() == initial_count


class TestSyncSingletonLocking:
    """Tests for thread-safe sync singleton resolution."""

    def test_sync_singleton_lock_creation(self) -> None:
        """Verify per-service locks are created correctly."""
        from diwire.service_key import ServiceKey

        container = Container(autoregister=True)

        class TestService:
            pass

        service_key = ServiceKey.from_value(TestService)

        # Lock should not exist before resolution
        assert service_key not in container._locks._sync_singleton_locks

        # Get a lock
        lock = container._locks.get_sync_singleton_lock(service_key)

        # Lock should now exist
        assert service_key in container._locks._sync_singleton_locks
        assert lock is container._locks._sync_singleton_locks[service_key]

        # Getting the same lock again should return the same object
        lock2 = container._locks.get_sync_singleton_lock(service_key)
        assert lock is lock2

    def test_sync_singleton_double_check_locking(self) -> None:
        """Test double-check locking with barrier synchronization."""
        container = Container(
            autoregister=True,
            autoregister_default_lifetime=Lifetime.SINGLETON,
            auto_compile=False,  # Disable compilation to test uncompiled path
        )

        class BarrierService:
            instance_count = 0

            def __init__(self) -> None:
                BarrierService.instance_count += 1

        barrier = threading.Barrier(20)
        results: list[BarrierService] = []

        def resolve_with_barrier() -> None:
            barrier.wait()  # All threads start together
            instance = container.resolve(BarrierService)
            results.append(instance)

        threads = [threading.Thread(target=resolve_with_barrier) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 20
        # Only one instance should have been created
        assert BarrierService.instance_count == 1
        # All results should be the same instance
        assert all(r is results[0] for r in results)

    def test_slow_singleton_only_created_once(self) -> None:
        """Singleton with delay in __init__ should only be created once."""
        import time

        container = Container(
            autoregister=True,
            autoregister_default_lifetime=Lifetime.SINGLETON,
            auto_compile=False,  # Test uncompiled path
        )

        class SlowSingleton:
            instance_count = 0

            def __init__(self) -> None:
                SlowSingleton.instance_count += 1
                time.sleep(0.05)  # Simulate slow initialization

        results: list[SlowSingleton] = []
        errors: list[Exception] = []

        def resolve_slow() -> None:
            try:
                instance = container.resolve(SlowSingleton)
                results.append(instance)
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(resolve_slow) for _ in range(20)]
            for f in as_completed(futures):
                f.result()

        assert not errors
        assert len(results) == 20
        # Only one instance should be created
        assert SlowSingleton.instance_count == 1
        # All results should be the same instance
        assert all(r is results[0] for r in results)


class TestCompiledProviderThreadSafety:
    """Tests for thread-safety of compiled singleton providers."""

    def test_singleton_type_provider_thread_safe(self) -> None:
        """SingletonTypeProvider should be thread-safe."""
        container = Container(
            autoregister=True,
            autoregister_default_lifetime=Lifetime.SINGLETON,
            auto_compile=True,
        )

        class CompiledSingleton:
            instance_count = 0

            def __init__(self) -> None:
                CompiledSingleton.instance_count += 1

        # Pre-compile the container
        container.register(CompiledSingleton, lifetime=Lifetime.SINGLETON)
        container.compile()

        barrier = threading.Barrier(20)
        results: list[CompiledSingleton] = []

        def resolve_compiled() -> None:
            barrier.wait()
            instance = container.resolve(CompiledSingleton)
            results.append(instance)

        threads = [threading.Thread(target=resolve_compiled) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 20
        assert CompiledSingleton.instance_count == 1
        assert all(r is results[0] for r in results)

    def test_singleton_args_provider_thread_safe(self) -> None:
        """SingletonArgsTypeProvider should be thread-safe."""
        container = Container(
            autoregister=True,
            autoregister_default_lifetime=Lifetime.SINGLETON,
            auto_compile=True,
        )

        class Dependency:
            pass

        class SingletonWithDeps:
            instance_count = 0

            def __init__(self, dep: Dependency) -> None:
                SingletonWithDeps.instance_count += 1
                self.dep = dep

        # Register and compile
        container.register(Dependency, lifetime=Lifetime.SINGLETON)
        container.register(SingletonWithDeps, lifetime=Lifetime.SINGLETON)
        container.compile()

        barrier = threading.Barrier(20)
        results: list[SingletonWithDeps] = []

        def resolve_with_deps() -> None:
            barrier.wait()
            instance = container.resolve(SingletonWithDeps)
            results.append(instance)

        threads = [threading.Thread(target=resolve_with_deps) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 20
        assert SingletonWithDeps.instance_count == 1
        assert all(r is results[0] for r in results)
        # Dependency should also be singleton
        assert all(r.dep is results[0].dep for r in results)

    def test_singleton_factory_provider_thread_safe(self) -> None:
        """SingletonFactoryProvider should be thread-safe."""
        container = Container(
            autoregister=False,
            auto_compile=True,
        )

        class FactorySingleton:
            instance_count = 0

            def __init__(self, value: int) -> None:
                FactorySingleton.instance_count += 1
                self.value = value

        class FactoryClass:
            call_count = 0

            def __call__(self) -> FactorySingleton:
                FactoryClass.call_count += 1
                return FactorySingleton(42)

        # Register with factory and compile
        container.register(FactoryClass)
        container.register(FactorySingleton, factory=FactoryClass, lifetime=Lifetime.SINGLETON)
        container.compile()

        barrier = threading.Barrier(20)
        results: list[FactorySingleton] = []

        def resolve_factory() -> None:
            barrier.wait()
            instance = container.resolve(FactorySingleton)
            results.append(instance)

        threads = [threading.Thread(target=resolve_factory) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 20
        assert FactorySingleton.instance_count == 1
        assert all(r is results[0] for r in results)
        assert results[0].value == 42
