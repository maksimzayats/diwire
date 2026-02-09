from __future__ import annotations

from collections.abc import Callable
from typing import Any

BENCHMARK_ITERATIONS = 100_000
BENCHMARK_WARMUP_ROUNDS = 3
BENCHMARK_ROUNDS = 5


def run_benchmark(
    benchmark: Any,
    target: Callable[[], None],
    *,
    iterations: int = BENCHMARK_ITERATIONS,
) -> None:
    benchmark.pedantic(
        target=target,
        warmup_rounds=BENCHMARK_WARMUP_ROUNDS,
        rounds=BENCHMARK_ROUNDS,
        iterations=iterations,
    )
