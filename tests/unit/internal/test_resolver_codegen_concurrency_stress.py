from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from diwire.container import Container
from diwire.providers import Lifetime

_THREAD_WORKERS = 12
_ASYNC_TASKS = 24


class _ThreadSingleton:
    pass


class _AsyncSingleton:
    pass


def test_concurrency_stress_thread_safe_singleton_constructs_once() -> None:
    calls = 0

    def build_singleton() -> _ThreadSingleton:
        nonlocal calls
        calls += 1
        return _ThreadSingleton()

    container = Container()
    container.register_factory(
        _ThreadSingleton,
        factory=build_singleton,
        lifetime=Lifetime.SINGLETON,
        concurrency_safe=True,
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
    container.register_factory(
        _ThreadSingleton,
        factory=build_singleton,
        lifetime=Lifetime.SINGLETON,
        concurrency_safe=False,
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


@pytest.mark.asyncio
async def test_concurrency_stress_async_safe_singleton_constructs_once() -> None:
    calls = 0

    async def build_singleton() -> _AsyncSingleton:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return _AsyncSingleton()

    container = Container()
    container.register_factory(
        _AsyncSingleton,
        factory=build_singleton,
        lifetime=Lifetime.SINGLETON,
        concurrency_safe=True,
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
    container.register_factory(
        _AsyncSingleton,
        factory=build_singleton,
        lifetime=Lifetime.SINGLETON,
        concurrency_safe=False,
    )

    results = await asyncio.gather(
        *(container.aresolve(_AsyncSingleton) for _ in range(_ASYNC_TASKS)),
    )

    assert calls == _ASYNC_TASKS
    assert len({id(result) for result in results}) == _ASYNC_TASKS
    assert await container.aresolve(_AsyncSingleton) is await container.aresolve(_AsyncSingleton)
