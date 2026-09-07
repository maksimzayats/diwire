"""Validate and evaluate the frozen H005 remote experiment protocol."""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any

# pytest-benchmark JSON is dynamic; validate its schema and values at this boundary.
JsonObject = dict[str, Any]
MEMORY_SIZES = (16, 64, 256)
MEMORY_METRICS = ("retained_bytes", "peak_bytes")


@dataclass(frozen=True)
class Effect:
    """Benefit-positive effects from independent process pairs."""

    headline: float
    paired: float
    wins: int
    baseline: tuple[float, ...]
    candidate: tuple[float, ...]

    def payload(self) -> JsonObject:
        return asdict(self)


def effect(pairs: list[tuple[float, float]], *, memory: bool) -> Effect:
    if not pairs:
        raise ValueError("An effect requires complete process pairs")
    if any(not math.isfinite(value) or value <= 0 for pair in pairs for value in pair):
        raise ValueError("Measurements must be positive finite numbers")
    baseline, candidate = zip(*pairs, strict=True)
    direction = -1 if memory else 1
    changes = [direction * 100 * (after / before - 1) for before, after in pairs]
    return Effect(
        headline=direction * 100 * (statistics.median(candidate) / statistics.median(baseline) - 1),
        paired=statistics.median(changes),
        wins=sum(change > 0 for change in changes),
        baseline=baseline,
        candidate=candidate,
    )


def outside_calibration(value: Effect, tolerance: float) -> bool:
    return abs(value.headline) > tolerance or abs(value.paired) > tolerance


def protection_flag(value: Effect, tolerance: float) -> bool:
    return value.headline < -tolerance or value.paired < -tolerance


def ambiguous(value: Effect, tolerance: float, band: float) -> bool:
    return (
        ((value.headline < -tolerance) != (value.paired < -tolerance))
        or abs(value.headline + tolerance) <= band
        or abs(value.paired + tolerance) <= band
    )


def validate_timing(data: JsonObject, expected: JsonObject) -> dict[str, float]:
    cells = data["benchmarks"]
    if len(cells) != len(expected) or {cell["fullname"] for cell in cells} != set(expected):
        raise ValueError("Unexpected or duplicate benchmark cells")
    result: dict[str, float] = {}
    for cell in cells:
        name = cell["fullname"]
        settings = expected[name]
        stats = cell["stats"]
        rounds = stats["data"]
        if (
            stats["rounds"] != settings["rounds"]
            or stats["iterations"] != settings["iterations"]
            or len(rounds) != settings["rounds"]
            or cell["options"] != settings["options"]
            or cell["extra_info"] != settings["extra_info"]
        ):
            msg = f"Sample counts or settings changed: {name}"
            raise ValueError(msg)
        if any(not math.isfinite(value) or value <= 0 for value in rounds):
            msg = f"Non-positive or non-finite round: {name}"
            raise ValueError(msg)
        mean = statistics.mean(rounds)
        if not math.isclose(stats["mean"], mean, rel_tol=1e-12) or not math.isclose(
            stats["ops"], 1 / mean, rel_tol=1e-12
        ):
            msg = f"Summary disagrees with retained rounds: {name}"
            raise ValueError(msg)
        result[name] = float(stats["ops"])
    return result


def validate_memory(data: JsonObject) -> dict[str, float]:
    rows = data["measurements"]
    if len(rows) != len(MEMORY_SIZES) or {row["provider_count"] for row in rows} != set(
        MEMORY_SIZES
    ):
        raise ValueError("Unexpected or duplicate memory sizes")
    expected_keys = {
        "provider_count",
        "retained_bytes",
        "peak_bytes",
        "generated_function_count",
        "unique_function_count",
        "unique_code_count",
        "unique_async_slot_function_count",
        "unique_async_slot_code_count",
        "unique_globals_count",
        "shallow_globals_dictionary_bytes",
    }
    result: dict[str, float] = {}
    for row in rows:
        if set(row) != expected_keys:
            raise ValueError("Unexpected memory fields")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in row.values()
        ):
            raise ValueError("Memory measurements and counts must be positive integers")
        size = row["provider_count"]
        total = 10 * size + 55
        if any(
            row[key] != total
            for key in ("generated_function_count", "unique_function_count", "unique_code_count")
        ):
            raise ValueError("Function or executable-code identities changed")
        if any(
            row[key] != 5 * size
            for key in ("unique_async_slot_function_count", "unique_async_slot_code_count")
        ):
            raise ValueError("Async slot function or code identities changed")
        if row["unique_globals_count"] != 1:
            raise ValueError("Generated namespaces changed")
        for metric in MEMORY_METRICS:
            value = row[metric]
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError("Memory measurements must be positive integers")
            result[f"{size}:{metric}"] = float(value)
    return result


def invariant_payload(
    data: JsonObject,
    *,
    memory: bool,
    compiler_hash: str,
    tree_hash: str,
    inputs: dict[str, str],
    checkpoint: str,
    power_label: str,
    require_harness: bool,
) -> JsonObject:
    source_name = "src/diwire/_internal/resolvers/assembly/compiler.py"
    expected_harness = {
        name.removeprefix("tests/performance/"): digest
        for name, digest in inputs.items()
        if name.startswith("tests/performance/")
    }
    if memory:
        expected_sources = {
            name: digest for name, digest in inputs.items() if name.startswith("src/")
        }
        expected_sources[source_name] = compiler_hash
        if (
            data["source_sha256"] != expected_sources
            or data["harness_sha256"] != expected_harness
            or data["benchmark_tree_sha256"] != tree_hash
        ):
            raise ValueError("Memory source or harness fingerprint mismatch")
        return {
            key: data[key]
            for key in (
                "python_version",
                "python_executable",
                "gil_enabled",
                "platform",
                "uv_lock_sha256",
                "harness_sha256",
            )
        }
    context = dict(data["diwire_benchmark_context"])
    harness = data.get("performance_harness_sha256")
    if (require_harness or harness is not None) and harness != expected_harness:
        raise ValueError("Timing performance harness fingerprint mismatch")
    if (
        data["commit_info"]["id"] != checkpoint
        or context.pop("benchmark_tree_sha256") != tree_hash
        or context["power_state"] != power_label
    ):
        raise ValueError("Timing source, harness, checkpoint or power label mismatch")
    return context
