from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from diwire import Container, Lifetime, LockMode, Scope

_THREAD_WORKERS = 12
_ASYNC_TASKS = 24


class _ThreadSingleton:
    pass


class _AsyncSingleton:
    pass


class _ThreadScoped:
    def __init__(self) -> None:
        self.initialized = False


class _ThreadScopedIntermediate:
    def __init__(self, dependency: _ThreadScoped) -> None:
        self.dependency = dependency


class _ThreadScopedConsumer:
    def __init__(self, intermediate: _ThreadScopedIntermediate) -> None:
        self.intermediate = intermediate

    @property
    def dependency(self) -> _ThreadScoped:
        return self.intermediate.dependency


class _ThreadFusionFiller:
    pass


class _AsyncScoped:
    pass


def test_concurrency_stress_thread_safe_singleton_constructs_once() -> None:
    calls = 0

    def build_singleton() -> _ThreadSingleton:
        nonlocal calls
        calls += 1
        return _ThreadSingleton()

    container = Container()
    container.add_factory(
        build_singleton,
        provides=_ThreadSingleton,
        lifetime=Lifetime.SCOPED,
        lock_mode=LockMode.THREAD,
    )
    container._root_resolver = container._resolvers_manager.build_root_resolver(
        container._root_scope,
        container._providers_registrations,
    )

    with ThreadPoolExecutor(max_workers=_THREAD_WORKERS) as pool:
        futures = [
            pool.submit(container.resolve, _ThreadSingleton) for _ in range(_THREAD_WORKERS * 2)
        ]
        results = [future.result() for future in futures]

    assert calls == 1
    assert len({id(result) for result in results}) == 1


def test_concurrency_stress_thread_unsafe_singleton_allows_parallel_construction() -> None:
    calls = 0
    all_started = threading.Event()
    calls_lock = threading.Lock()

    def build_singleton() -> _ThreadSingleton:
        nonlocal calls
        with calls_lock:
            calls += 1
            if calls == _THREAD_WORKERS:
                all_started.set()
        did_start = all_started.wait(timeout=2)
        assert did_start
        return _ThreadSingleton()

    container = Container()
    container.add_factory(
        build_singleton,
        provides=_ThreadSingleton,
        lifetime=Lifetime.SCOPED,
        lock_mode=LockMode.NONE,
    )
    container._root_resolver = container._resolvers_manager.build_root_resolver(
        container._root_scope,
        container._providers_registrations,
    )

    with ThreadPoolExecutor(max_workers=_THREAD_WORKERS) as pool:
        futures = [pool.submit(container.resolve, _ThreadSingleton) for _ in range(_THREAD_WORKERS)]
        results = [future.result() for future in futures]

    assert calls == _THREAD_WORKERS
    assert len({id(result) for result in results}) == _THREAD_WORKERS
    assert container.resolve(_ThreadSingleton) is container.resolve(_ThreadSingleton)


def test_concurrency_stress_thread_safe_scoped_constructs_once_per_scope() -> None:
    calls = 0

    def build_scoped() -> _ThreadScoped:
        nonlocal calls
        calls += 1
        return _ThreadScoped()

    container = Container()
    container.add_factory(
        build_scoped,
        provides=_ThreadScoped,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
        lock_mode=LockMode.THREAD,
    )
    container._root_resolver = container._resolvers_manager.build_root_resolver(
        container._root_scope,
        container._providers_registrations,
    )

    with container.enter_scope(Scope.REQUEST) as request_scope:
        with ThreadPoolExecutor(max_workers=_THREAD_WORKERS) as pool:
            futures = [
                pool.submit(request_scope.resolve, _ThreadScoped)
                for _ in range(_THREAD_WORKERS * 2)
            ]
            first_scope_results = [future.result() for future in futures]

        assert calls == 1
        assert len({id(result) for result in first_scope_results}) == 1
        assert request_scope.resolve(_ThreadScoped) is first_scope_results[0]

    with container.enter_scope(Scope.REQUEST) as second_scope:
        second_scope_value = second_scope.resolve(_ThreadScoped)
        assert second_scope_value is second_scope.resolve(_ThreadScoped)
        assert second_scope_value is not first_scope_results[0]

    assert calls == 2


def test_concurrency_stress_current_scope_dependency_fast_path_publishes_once() -> None:
    calls = 0

    def build_scoped() -> _ThreadScoped:
        nonlocal calls
        calls += 1
        dependency = _ThreadScoped()
        dependency.initialized = True
        return dependency

    container = Container(use_resolver_context=False)
    container.add_factory(
        build_scoped,
        provides=_ThreadScoped,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
        lock_mode=LockMode.THREAD,
    )
    container.add(
        _ThreadScopedIntermediate,
        provides=_ThreadScopedIntermediate,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )
    container.add(
        _ThreadScopedConsumer,
        provides=_ThreadScopedConsumer,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )
    container.add(
        _ThreadFusionFiller,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )
    container.compile()
    start = threading.Barrier(_THREAD_WORKERS)

    with container.enter_scope(Scope.REQUEST) as request_scope:
        consumer_slot = container._providers_registrations.get_by_type(
            _ThreadScopedConsumer,
        ).slot
        assert f"_provider_{consumer_slot}" in request_scope.resolve.__code__.co_names
        assert f"resolve_{consumer_slot}" not in request_scope.resolve.__code__.co_names

        def resolve_consumer() -> _ThreadScopedConsumer:
            start.wait()
            return request_scope.resolve(_ThreadScopedConsumer)

        with ThreadPoolExecutor(max_workers=_THREAD_WORKERS) as pool:
            futures = [pool.submit(resolve_consumer) for _ in range(_THREAD_WORKERS)]
            consumers = [future.result() for future in futures]

        dependencies = [consumer.dependency for consumer in consumers]
        assert calls == 1
        assert len({id(consumer) for consumer in consumers}) == _THREAD_WORKERS
        assert len({id(consumer.intermediate) for consumer in consumers}) == _THREAD_WORKERS
        assert all(dependency is dependencies[0] for dependency in dependencies)
        assert all(dependency.initialized for dependency in dependencies)
        assert request_scope.resolve(_ThreadScopedConsumer).dependency is dependencies[0]

    with container.enter_scope(Scope.REQUEST) as second_scope:
        second_dependency = second_scope.resolve(_ThreadScopedConsumer).dependency

    assert second_dependency is not dependencies[0]
    assert second_dependency.initialized
    assert calls == 2


def test_concurrency_stress_thread_unsafe_scoped_allows_parallel_construction() -> None:
    calls = 0
    all_started = threading.Event()
    calls_lock = threading.Lock()

    def build_scoped() -> _ThreadScoped:
        nonlocal calls
        with calls_lock:
            calls += 1
            if calls == _THREAD_WORKERS:
                all_started.set()
        did_start = all_started.wait(timeout=2)
        assert did_start
        return _ThreadScoped()

    container = Container()
    container.add_factory(
        build_scoped,
        provides=_ThreadScoped,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
        lock_mode=LockMode.NONE,
    )
    container._root_resolver = container._resolvers_manager.build_root_resolver(
        container._root_scope,
        container._providers_registrations,
    )

    with container.enter_scope(Scope.REQUEST) as request_scope:
        with ThreadPoolExecutor(max_workers=_THREAD_WORKERS) as pool:
            futures = [
                pool.submit(request_scope.resolve, _ThreadScoped) for _ in range(_THREAD_WORKERS)
            ]
            results = [future.result() for future in futures]

        assert calls == _THREAD_WORKERS
        assert len({id(result) for result in results}) == _THREAD_WORKERS
        assert request_scope.resolve(_ThreadScoped) is request_scope.resolve(_ThreadScoped)


def test_concurrency_stress_thread_unsafe_scoped_from_default_allows_parallel_construction() -> (
    None
):
    calls = 0
    all_started = threading.Event()
    calls_lock = threading.Lock()

    def build_scoped() -> _ThreadScoped:
        nonlocal calls
        with calls_lock:
            calls += 1
            if calls == _THREAD_WORKERS:
                all_started.set()
        did_start = all_started.wait(timeout=2)
        assert did_start
        return _ThreadScoped()

    container = Container(lock_mode=LockMode.NONE)
    container.add_factory(
        build_scoped,
        provides=_ThreadScoped,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container._root_resolver = container._resolvers_manager.build_root_resolver(
        container._root_scope,
        container._providers_registrations,
    )

    with container.enter_scope(Scope.REQUEST) as request_scope:
        with ThreadPoolExecutor(max_workers=_THREAD_WORKERS) as pool:
            futures = [
                pool.submit(request_scope.resolve, _ThreadScoped) for _ in range(_THREAD_WORKERS)
            ]
            results = [future.result() for future in futures]

        assert calls == _THREAD_WORKERS
        assert len({id(result) for result in results}) == _THREAD_WORKERS
        assert request_scope.resolve(_ThreadScoped) is request_scope.resolve(_ThreadScoped)


@pytest.mark.asyncio
async def test_concurrency_stress_async_safe_singleton_constructs_once() -> None:
    calls = 0

    async def build_singleton() -> _AsyncSingleton:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return _AsyncSingleton()

    container = Container()
    container.add_factory(
        build_singleton,
        provides=_AsyncSingleton,
        lifetime=Lifetime.SCOPED,
        lock_mode=LockMode.ASYNC,
    )

    results = await asyncio.gather(
        *(container.aresolve(_AsyncSingleton) for _ in range(_ASYNC_TASKS)),
    )

    assert calls == 1
    assert len({id(result) for result in results}) == 1


@pytest.mark.asyncio
async def test_concurrency_stress_async_unsafe_singleton_allows_parallel_construction() -> None:
    calls = 0
    all_started = asyncio.Event()

    async def build_singleton() -> _AsyncSingleton:
        nonlocal calls
        calls += 1
        if calls == _ASYNC_TASKS:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=2)
        return _AsyncSingleton()

    container = Container()
    container.add_factory(
        build_singleton,
        provides=_AsyncSingleton,
        lifetime=Lifetime.SCOPED,
        lock_mode=LockMode.NONE,
    )

    results = await asyncio.gather(
        *(container.aresolve(_AsyncSingleton) for _ in range(_ASYNC_TASKS)),
    )

    assert calls == _ASYNC_TASKS
    assert len({id(result) for result in results}) == _ASYNC_TASKS
    assert await container.aresolve(_AsyncSingleton) is await container.aresolve(_AsyncSingleton)


@pytest.mark.asyncio
async def test_concurrency_stress_async_safe_scoped_constructs_once_per_scope() -> None:
    calls = 0

    async def build_scoped() -> _AsyncScoped:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return _AsyncScoped()

    container = Container()
    container.add_factory(
        build_scoped,
        provides=_AsyncScoped,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
        lock_mode=LockMode.ASYNC,
    )

    async with container.enter_scope(Scope.REQUEST) as request_scope:
        first_scope_results = await asyncio.gather(
            *(request_scope.aresolve(_AsyncScoped) for _ in range(_ASYNC_TASKS)),
        )

        assert calls == 1
        assert len({id(result) for result in first_scope_results}) == 1
        assert await request_scope.aresolve(_AsyncScoped) is first_scope_results[0]

    async with container.enter_scope(Scope.REQUEST) as second_scope:
        second_scope_value = await second_scope.aresolve(_AsyncScoped)
        assert second_scope_value is await second_scope.aresolve(_AsyncScoped)
        assert second_scope_value is not first_scope_results[0]

    assert calls == 2


@pytest.mark.asyncio
async def test_concurrency_stress_async_unsafe_scoped_allows_parallel_construction() -> None:
    calls = 0
    all_started = asyncio.Event()

    async def build_scoped() -> _AsyncScoped:
        nonlocal calls
        calls += 1
        if calls == _ASYNC_TASKS:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=2)
        return _AsyncScoped()

    container = Container()
    container.add_factory(
        build_scoped,
        provides=_AsyncScoped,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
        lock_mode=LockMode.NONE,
    )

    async with container.enter_scope(Scope.REQUEST) as request_scope:
        results = await asyncio.gather(
            *(request_scope.aresolve(_AsyncScoped) for _ in range(_ASYNC_TASKS)),
        )

        assert calls == _ASYNC_TASKS
        assert len({id(result) for result in results}) == _ASYNC_TASKS
        assert await request_scope.aresolve(_AsyncScoped) is await request_scope.aresolve(
            _AsyncScoped,
        )


@pytest.mark.asyncio
async def test_concurrency_stress_async_unsafe_scoped_from_default_allows_parallel_construction() -> (
    None
):
    calls = 0
    all_started = asyncio.Event()

    async def build_scoped() -> _AsyncScoped:
        nonlocal calls
        calls += 1
        if calls == _ASYNC_TASKS:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=2)
        return _AsyncScoped()

    container = Container(lock_mode=LockMode.NONE)
    container.add_factory(
        build_scoped,
        provides=_AsyncScoped,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    async with container.enter_scope(Scope.REQUEST) as request_scope:
        results = await asyncio.gather(
            *(request_scope.aresolve(_AsyncScoped) for _ in range(_ASYNC_TASKS)),
        )

        assert calls == _ASYNC_TASKS
        assert len({id(result) for result in results}) == _ASYNC_TASKS
        assert await request_scope.aresolve(_AsyncScoped) is await request_scope.aresolve(
            _AsyncScoped,
        )
