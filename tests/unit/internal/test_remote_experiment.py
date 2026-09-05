from __future__ import annotations

import gzip
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType
from typing import Any, cast

import pytest

from tests.performance import remote_experiment as runner
from tests.performance.remote_experiment_results import (
    Effect,
    JsonObject,
    ambiguous,
    effect,
    invariant_payload,
    outside_calibration,
    protection_flag,
    validate_memory,
    validate_timing,
)


def _effect(headline: float, paired: float | None = None) -> Effect:
    return Effect(headline, headline if paired is None else paired, 5, (), ())


def _experiment(tmp_path: Path) -> runner.Experiment:
    experiment = object.__new__(runner.Experiment)
    experiment.subject = tmp_path
    experiment.output = tmp_path
    experiment.source = tmp_path / runner._SOURCE
    experiment.cache = tmp_path / "cache"
    experiment.cache.mkdir()
    experiment.restoration_allowed = True
    experiment.deadline = time.monotonic() + 30
    experiment.protocol = {
        "maximum_child_seconds": 5,
        "protection_percent": 2,
        "confirmation_boundary_band": 0.25,
    }
    experiment.pair_values = {}
    return experiment


def test_effect_uses_all_pairs_and_preserves_pairing() -> None:
    pairs = [(100.0, 101.0), (200.0, 204.0), (300.0, 330.0)]
    result = effect(pairs, memory=False)
    assert result.headline == pytest.approx(2)
    assert result.paired == pytest.approx(2)
    assert result.wins == 3
    assert list(result.baseline) == [100, 200, 300]
    assert effect(pairs, memory=True).headline == pytest.approx(-2)
    assert effect(pairs, memory=True).wins == 0


@pytest.mark.parametrize("pairs", [[], [(0, 1)], [(1, float("nan"))], [(1, float("inf"))]])
def test_effect_rejects_invalid_observations(pairs: list[tuple[float, float]]) -> None:
    with pytest.raises(ValueError, match=r"complete process pairs|positive finite"):
        effect(pairs, memory=False)


def test_thresholds_remain_unrounded_and_ambiguity_does_not_relax_them() -> None:
    assert not outside_calibration(_effect(2, -2), 2)
    assert outside_calibration(_effect(0.93, 2.002987408764212), 2)
    assert protection_flag(_effect(-2.00000001, -1), 2)
    assert not protection_flag(_effect(-2), 2)
    assert ambiguous(_effect(-1, -3), 2, 0.25)
    assert ambiguous(_effect(-1.75), 2, 0.25)
    assert not ambiguous(_effect(-3), 2, 0.25)


def _timing() -> tuple[JsonObject, JsonObject]:
    settings = {"rounds": 2, "iterations": 100, "options": {}, "extra_info": {}}
    return {
        "benchmarks": [
            {
                "fullname": "cell",
                "options": {},
                "extra_info": {},
                "stats": {"rounds": 2, "iterations": 100, "data": [1, 3], "mean": 2, "ops": 0.5},
            }
        ],
    }, {"cell": settings}


def test_timing_checks_raw_rounds_and_exact_workloads() -> None:
    data, expected = _timing()
    assert validate_timing(data, expected) == {"cell": 0.5}
    data["benchmarks"][0]["stats"]["mean"] = 3
    with pytest.raises(ValueError, match="Summary disagrees"):
        validate_timing(data, expected)
    data, expected = _timing()
    data["benchmarks"].append(data["benchmarks"][0])
    with pytest.raises(ValueError, match="duplicate"):
        validate_timing(data, expected)


def _memory() -> JsonObject:
    return {
        "measurements": [
            {
                "provider_count": size,
                "retained_bytes": 1000,
                "peak_bytes": 2000,
                "generated_function_count": 10 * size + 55,
                "unique_function_count": 10 * size + 55,
                "unique_code_count": 10 * size + 55,
                "unique_async_slot_function_count": 5 * size,
                "unique_async_slot_code_count": 5 * size,
                "unique_globals_count": 1,
                "shallow_globals_dictionary_bytes": 100,
            }
            for size in (16, 64, 256)
        ]
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unique_code_count", 1),
        ("unique_code_count", 215.0),
        ("unique_globals_count", True),
        ("unique_async_slot_code_count", 1),
        ("retained_bytes", -1),
    ],
)
def test_memory_requires_distinct_identities_and_integer_measurements(
    field: str, value: object
) -> None:
    data = _memory()
    assert len(validate_memory(data)) == 6
    data["measurements"][0][field] = value
    with pytest.raises(ValueError, match=r"identities|positive integers"):
        validate_memory(data)


def test_input_hashes_allow_absent_optional_files_and_detect_their_appearance(
    tmp_path: Path,
) -> None:
    experiment = _experiment(tmp_path)
    for name in ("pyproject.toml", "uv.lock", "tools/performance_ledger.py", runner._SOURCE):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frozen")
    before = experiment._input_hashes()
    assert ".python-version" not in before
    assert "tests/conftest.py" not in before
    (tmp_path / ".python-version").write_text("3.14.6")
    assert experiment._input_hashes() != before
    (tmp_path / "uv.lock").unlink()
    with pytest.raises(FileNotFoundError):
        experiment._input_hashes()


def _context() -> JsonObject:
    return {
        "commit_info": {"id": "checkpoint"},
        "diwire_benchmark_context": {"benchmark_tree_sha256": "tree", "power_state": "power"},
    }


def test_canonical_only_confirmation_uses_frozen_input_hashes_without_optional_hook() -> None:
    arguments: JsonObject = {
        "memory": False,
        "compiler_hash": "compiler",
        "tree_hash": "tree",
        "inputs": {"tests/performance/conftest.py": "hash"},
        "checkpoint": "checkpoint",
        "power_label": "power",
    }
    data = _context()
    assert invariant_payload(data, require_harness=False, **arguments) == {"power_state": "power"}
    with pytest.raises(ValueError, match="harness"):
        invariant_payload(data, require_harness=True, **arguments)
    data["performance_harness_sha256"] = {"conftest.py": "wrong"}
    with pytest.raises(ValueError, match="harness"):
        invariant_payload(data, require_harness=False, **arguments)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("python_version", "3.14.5"),
        ("python_executable", "/wrong/python"),
        ("gil_mode", "disabled"),
        ("uv_lock_sha256", "wrong"),
    ],
)
def test_read_run_rejects_consistently_wrong_child_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    experiment = _experiment(tmp_path)
    experiment.baseline = b"baseline"
    experiment.candidate = b"candidate"
    experiment.base_tree = "tree"
    experiment.inputs = {}
    experiment.anchors = {}
    experiment.protocol.update(
        subject_commit="checkpoint", python_version="3.14.6", lock_sha256="lock"
    )
    context = {
        "python_version": "3.14.6",
        "python_executable": str((tmp_path / ".venv/bin/python").resolve()),
        "gil_mode": "enabled",
        "uv_lock_sha256": "lock",
    }
    context[field] = value
    monkeypatch.setattr(runner, "invariant_payload", lambda *_args, **_kwargs: context)
    path = tmp_path / "run.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="frozen protocol"):
        experiment._read_run(path, memory=False, candidate=False, nodes=[])


def test_confirmation_stages_both_groups_before_one_extension_wave(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = _experiment(tmp_path)
    calls: list[tuple[str, int]] = []

    def series(
        label: str, *, memory: bool, comparison: bool, nodes: list[str], start_pair: int = 1
    ) -> dict[str, Effect]:
        calls.append((label, start_pair))
        name = "16:peak_bytes" if memory else "timing"
        # First five are ambiguous. All ten pass when recomputed together.
        pair = (100.0, 102.0 if memory else 98.0) if start_pair == 1 else (100.0, 100.0)
        experiment.pair_values[label] = {name: [pair] * 5}
        return {name: effect([pair] * 5, memory=memory)}

    monkeypatch.setattr(experiment, "series", series)
    assert runner._confirm(experiment, {True: {"16:peak_bytes"}, False: {"timing"}}) == "pass"
    assert calls == [
        ("memory-confirmation", 1),
        ("timing-confirmation", 1),
        ("memory-confirmation-extension", 6),
        ("timing-confirmation-extension", 6),
    ]
    combined = json.loads((tmp_path / "confirmation-combined.json").read_text())
    assert len(combined["timing"]["baseline"]) == 10
    assert combined["timing"]["headline"] == pytest.approx(-1)


def test_clear_confirmation_failure_prevents_every_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = _experiment(tmp_path)
    calls: list[str] = []

    def series(label: str, **kwargs: object) -> dict[str, Effect]:
        calls.append(label)
        return {"memory": _effect(-2), "timing": _effect(-3)}

    monkeypatch.setattr(experiment, "series", series)
    assert runner._confirm(experiment, {True: {"memory"}, False: {"timing"}}) == "rejected"
    assert calls == ["memory-confirmation", "timing-confirmation"]


def test_failed_calibration_stops_without_comparisons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = _experiment(tmp_path)
    experiment.protocol["calibration_cells"] = ["cell"]
    calls: list[str] = []

    def series(label: str, **kwargs: object) -> dict[str, Effect]:
        calls.append(label)
        return {"cell": _effect(2.002987)}

    monkeypatch.setattr(experiment, "series", series)
    assert runner._evaluate(experiment) == "deferred: timing calibration failed"
    assert calls == ["timing-aa"]


@pytest.mark.skipif(os.name != "posix", reason="Requires POSIX process groups and signals")
def test_normal_exit_cleans_up_surviving_descendant(tmp_path: Path) -> None:
    experiment = _experiment(tmp_path)
    entry: JsonObject = {}
    code = "import os,time\nif os.fork() == 0: time.sleep(60)\nelse: os._exit(0)\n"
    with (tmp_path / "child.log").open("w") as log:
        assert experiment._run_child([sys.executable, "-c", code], log, entry) == 0
    assert experiment.restoration_allowed
    assert entry["child_cleanup_verified"]


@pytest.mark.skipif(os.name != "posix", reason="Requires POSIX process groups and signals")
def test_launch_interrupt_is_deferred_until_child_is_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = _experiment(tmp_path)
    real_popen = subprocess.Popen
    originals = {
        control: signal.getsignal(control)
        for control in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    }

    def launch(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
        child = real_popen(*args, **kwargs)
        if kwargs.get("start_new_session"):
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            handler(signal.SIGTERM, cast("FrameType", None))
        return child

    monkeypatch.setattr(subprocess, "Popen", launch)
    entry: JsonObject = {}
    try:
        with (tmp_path / "child.log").open("w") as log, pytest.raises(KeyboardInterrupt):
            experiment._run_child([sys.executable, "-c", "import time; time.sleep(60)"], log, entry)
    finally:
        for control, handler in originals.items():
            signal.signal(control, handler)
    assert entry["child_cleanup_verified"]
    assert experiment.restoration_allowed


@pytest.mark.skipif(os.name != "posix", reason="Requires POSIX process groups and signals")
def test_initialization_failure_is_persisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "experiment",
            "--subject",
            str(tmp_path),
            "--output",
            str(output),
            "--protocol",
            str(tmp_path / "missing.json"),
            "--archive",
            str(tmp_path / "archive.gz"),
        ],
    )
    # Avoid changing the test runner's process signal handlers.
    monkeypatch.setattr(signal, "signal", lambda *_args: None)
    assert runner.main() == 1
    report = json.loads((output / "decision.json").read_text())
    assert report["error"]["type"] == "FileNotFoundError"
    assert report["phase"] == "initialization"
    assert report["source_restored"] is None


def test_candidate_inspection_always_restores_after_fingerprint_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = _experiment(tmp_path)
    experiment.source.parent.mkdir(parents=True)
    experiment.source.write_bytes(b"baseline")
    experiment.baseline = b"baseline"
    monkeypatch.setattr(experiment, "_apply", lambda: experiment.source.write_bytes(b"candidate"))
    monkeypatch.setattr(
        experiment, "restore", lambda: experiment.source.write_bytes(experiment.baseline)
    )

    def fail(path: Path) -> str:
        raise ValueError("broken fingerprint")

    monkeypatch.setattr(runner, "compute_benchmark_tree_fingerprint", fail)
    with pytest.raises(ValueError, match="broken fingerprint"):
        experiment._candidate_bytes()
    assert experiment.source.read_bytes() == b"baseline"


def test_validators_accept_archived_raw_rounds_and_memory_identities() -> None:
    evidence = Path(__file__).parents[3] / ".agents/performance-evidence/2026-09-05"
    protocol = json.loads((evidence / "h005-linux-protocol.json").read_text())
    timing = json.loads(gzip.decompress((evidence / "h004-calibration.json.gz").read_bytes()))
    for run in timing["runs"]:
        cells = [{"fullname": cell["name"], **cell} for cell in run["measurements"]]
        expected = {cell["fullname"]: protocol["timing_cells"][cell["fullname"]] for cell in cells}
        assert len(validate_timing({"benchmarks": cells}, expected)) == 12
    memory = json.loads(gzip.decompress((evidence / "h005-allocation.json.gz").read_bytes()))
    for series in memory["series"].values():
        for run in series["runs"]:
            assert len(validate_memory(run["data"])) == 6


@pytest.mark.skipif(os.name != "posix", reason="Requires POSIX process groups and signals")
def test_restoration_failure_keeps_primary_error_and_cleanup_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = _experiment(tmp_path)
    experiment.phase = "timing-aa"
    experiment.baseline = b"baseline"
    experiment.source.parent.mkdir(parents=True)
    experiment.source.write_bytes(b"candidate")
    experiment.restoration_allowed = False
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "experiment",
            "--subject",
            str(tmp_path),
            "--output",
            str(output),
            "--protocol",
            "protocol",
            "--archive",
            "archive",
        ],
    )
    monkeypatch.setattr(signal, "signal", lambda *_args: None)
    monkeypatch.setattr(runner, "Experiment", lambda **_kwargs: experiment)

    def fail(protocol: Path, archive: Path) -> None:
        raise ValueError("primary failure")

    monkeypatch.setattr(experiment, "prepare", fail)
    assert runner.main() == 1
    report = json.loads((output / "decision.json").read_text())
    assert report["error"]["message"] == "primary failure"
    assert report["restoration_error"]["type"] == "RuntimeError"
    assert not report["child_cleanup_verified"]
    assert not report["source_restored"]
    assert report["phase"] == "timing-aa"
