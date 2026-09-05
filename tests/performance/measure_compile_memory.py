"""Record compiler allocations separately from uninstrumented timing runs."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import sys
import tracemalloc
from pathlib import Path
from types import FunctionType
from typing import Any, cast

from tests.performance.test_compile_workloads import make_compile_workload
from tools.performance_ledger import compute_benchmark_tree_fingerprint


def measure_compile_memory(provider_count: int) -> dict[str, int]:
    container, _services = make_compile_workload(provider_count)
    gc.collect()
    tracemalloc.start(1)
    try:
        initial, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        resolver = container.compile()
        _, peak = tracemalloc.get_traced_memory()
        gc.collect()
        retained, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # Generated class metadata is private and absent from ResolverProtocol.
    runtime = cast("Any", resolver)._runtime
    namespaces: dict[int, dict[str, object]] = {}
    generated_function_count = 0
    for resolver_class in runtime.class_by_level.values():
        for member in vars(resolver_class).values():
            if isinstance(member, FunctionType):
                generated_function_count += 1
                namespaces[id(member.__globals__)] = member.__globals__
    result = {
        "provider_count": provider_count,
        "retained_bytes": retained - initial,
        "peak_bytes": peak - initial,
        "generated_function_count": generated_function_count,
        "unique_globals_count": len(namespaces),
        "shallow_globals_dictionary_bytes": sum(
            sys.getsizeof(value) for value in namespaces.values()
        ),
    }
    container.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).parents[2]
    harness = Path(__file__).parent
    result = {
        "python_version": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: True)(),
        "platform": platform.platform(),
        "benchmark_tree_sha256": compute_benchmark_tree_fingerprint(root),
        "uv_lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
        "source_sha256": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((root / "src").rglob("*.py"))
        },
        "harness_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(harness.glob("*.py"))
        },
        "measurements": [measure_compile_memory(count) for count in (16, 64, 256)],
    }
    with args.output.open("x") as output:
        json.dump(result, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
