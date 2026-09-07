from __future__ import annotations

import hashlib
from pathlib import Path

from tests.benchmarks import conftest as canonical_benchmarks


def pytest_benchmark_update_json(output_json: dict[str, object]) -> None:
    """Record both canonical and extended benchmark inputs in raw evidence."""
    canonical_benchmarks.pytest_benchmark_update_json(output_json)
    directory = Path(__file__).parent
    output_json["performance_harness_sha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.glob("*.py"))
    }
