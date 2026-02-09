from __future__ import annotations

import timeit
from typing import Any

import rodi

from diwire.container import Container as DIWireContainer

_TIMEIT_NUMBER = 100_000
_WARMUP_ROUNDS = 3
_MEASURE_ROUNDS = 5


def test_diwire_scope_open_close_is_faster_than_rodi(benchmark: Any) -> None:
    # Keep benchmark fixture in use so --benchmark-skip gates this test.
    benchmark(lambda: None)

    container = DIWireContainer(default_concurrency_safe=False)
    container.register_instance(int, instance=42)

    with container.enter_scope() as scoped_container:
        scoped_container.resolve(int)

    def bench_diwire() -> None:
        with container.enter_scope() as scoped_container:
            _ = scoped_container.resolve(int)

    rodi_container = rodi.Container()
    rodi_container.add_singleton_by_factory(lambda: 42, int)
    services = rodi_container.build_provider()
    services.get(int)

    def bench_rodi() -> None:
        with services.create_scope() as scoped_services:
            _ = scoped_services.get(int)

    for _ in range(_WARMUP_ROUNDS):
        timeit.timeit(stmt=bench_diwire, number=_TIMEIT_NUMBER)
        timeit.timeit(stmt=bench_rodi, number=_TIMEIT_NUMBER)

    diwire_runs = [
        timeit.timeit(stmt=bench_diwire, number=_TIMEIT_NUMBER) for _ in range(_MEASURE_ROUNDS)
    ]
    rodi_runs = [
        timeit.timeit(stmt=bench_rodi, number=_TIMEIT_NUMBER) for _ in range(_MEASURE_ROUNDS)
    ]

    diwire_best = min(diwire_runs)
    rodi_best = min(rodi_runs)

    assert diwire_best < rodi_best, (
        "diwire must be faster than rodi for the scope open/close timeit scenario. "
        f"diwire_best={diwire_best:.6f}, rodi_best={rodi_best:.6f}, ratio={rodi_best / diwire_best:.3f}"
    )
