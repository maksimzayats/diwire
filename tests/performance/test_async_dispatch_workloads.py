from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from diwire import Lifetime, Scope
from tests.benchmarks.helpers import make_diwire_benchmark_container
from tests.performance.test_aresolve_workloads import _BATCH_SIZE, _run_async_benchmark


class _TransientService:
    pass


class _CachedService:
    pass


def _transient_numbers() -> list[int]:
    return [1]


def _cached_names() -> list[str]:
    return ["cached"]


@pytest.mark.parametrize(
    "pattern_name",
    [
        "same_identity",
        "same_equality",
        "alternate_identity_equality",
        "alternate_equal_aliases",
        "mixed_cached",
    ],
)
def test_benchmark_diwire_aresolve_dispatch_patterns(benchmark: Any, pattern_name: str) -> None:
    registered_numbers = list[int]
    first_alias = list[int]
    second_alias = list[int]
    cached_alias = list[str]
    assert registered_numbers == first_alias == second_alias
    assert registered_numbers is not first_alias
    assert registered_numbers is not second_alias
    assert first_alias is not second_alias

    container = make_diwire_benchmark_container()
    container.add(_TransientService, lifetime=Lifetime.TRANSIENT, scope=Scope.APP)
    container.add(_CachedService, lifetime=Lifetime.SCOPED, scope=Scope.APP)
    container.add_factory(
        _transient_numbers,
        provides=registered_numbers,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
    )
    container.add_factory(
        _cached_names, provides=cached_alias, lifetime=Lifetime.SCOPED, scope=Scope.APP
    )
    resolver = container.compile()
    patterns: dict[str, tuple[object, ...]] = {
        "same_identity": (_TransientService,),
        "same_equality": (first_alias,),
        "alternate_identity_equality": (_TransientService, first_alias),
        "alternate_equal_aliases": (first_alias, second_alias),
        "mixed_cached": (_TransientService, _CachedService, first_alias, cached_alias),
    }
    pattern = patterns[pattern_name]
    assert _BATCH_SIZE % len(pattern) == 0
    keys = pattern * (_BATCH_SIZE // len(pattern))
    benchmark.extra_info["dispatch_pattern"] = pattern_name

    async def check() -> None:
        # Generated dispatch-cache attributes are absent from the public protocol.
        generated_resolver = cast("Any", resolver)
        first = await resolver.aresolve(_TransientService)
        assert isinstance(first, _TransientService)
        assert first is not await resolver.aresolve(_TransientService)
        assert cast("object", generated_resolver._last_async_dependency) is _TransientService
        first_numbers = await resolver.aresolve(first_alias)
        assert first_numbers == [1]
        assert first_numbers is not await resolver.aresolve(first_alias)
        assert cast("object", generated_resolver._last_async_dependency) is first_alias
        second_numbers = await resolver.aresolve(second_alias)
        assert second_numbers == first_numbers
        assert second_numbers is not first_numbers
        assert cast("object", generated_resolver._last_async_dependency) is second_alias
        previous_method = generated_resolver._last_async_method
        cached = await resolver.aresolve(_CachedService)
        assert isinstance(cached, _CachedService)
        assert cached is await resolver.aresolve(_CachedService)
        names = await resolver.aresolve(cached_alias)
        assert names == ["cached"]
        assert names is await resolver.aresolve(cached_alias)
        assert cast("object", generated_resolver._last_async_dependency) is second_alias
        assert generated_resolver._last_async_method is previous_method

    async def batch() -> None:
        for key in keys:
            await resolver.aresolve(key)

    try:
        asyncio.run(check())
        _run_async_benchmark(benchmark, batch)
    finally:
        asyncio.run(resolver.aclose())
