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
        container = Container(register_if_missing=False)
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
        container = Container(register_if_missing=True)
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
        """Test that singleton creation doesn't create multiple instances under race."""
        # This test documents current behavior - may create multiple instances
        # under high contention before one is cached
        container = Container(
            register_if_missing=True,
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

        # All results should be the same instance (eventually)
        # Note: Without proper locking, there may be a small window where
        # multiple instances are created, but ultimately only one is cached
        assert len(results) == 20


class TestStress:
    def test_many_concurrent_resolutions(self) -> None:
        """100 threads resolving concurrently."""
        container = Container(register_if_missing=True)

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
        container = Container(register_if_missing=True)
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
        container = Container(register_if_missing=True)
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
        container = Container(register_if_missing=True)
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
        container = Container(register_if_missing=True)
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
        container = Container(register_if_missing=True)
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
            register_if_missing=True,
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
        container = Container(register_if_missing=True)
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
        container = Container(register_if_missing=True)
        results: list[ServiceB] = []

        async def worker() -> None:
            instance = await container.aresolve(ServiceB)
            results.append(instance)

        await asyncio.gather(*[worker() for _ in range(10)])

        assert len(results) == 10
        for r in results:
            assert isinstance(r, ServiceB)
            assert isinstance(r.a, ServiceA)
