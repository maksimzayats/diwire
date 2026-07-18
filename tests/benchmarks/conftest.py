from __future__ import annotations

from pathlib import Path
from typing import cast

from tools.performance_ledger import BENCHMARK_CONTEXT_KEY, build_benchmark_context

_REPO_ROOT = Path(__file__).parents[2]


def pytest_benchmark_update_json(output_json: dict[str, object]) -> None:
    """Embed the exact benchmark input tree and environment in raw JSON artifacts."""
    machine_info_value = output_json.get("machine_info")
    if not isinstance(machine_info_value, dict):
        msg = "pytest-benchmark JSON does not contain machine_info."
        raise TypeError(msg)
    machine_info = cast("dict[str, object]", machine_info_value)
    output_json[BENCHMARK_CONTEXT_KEY] = build_benchmark_context(
        repo_root=_REPO_ROOT,
        machine_info=machine_info,
    )
