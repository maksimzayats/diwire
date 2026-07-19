from __future__ import annotations

import ast
import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from tools.performance_ledger import (
    CompetitiveScore,
    IndependentRun,
    PerformanceLedgerError,
    RunStats,
    build_ledger_record,
    compare_scores,
    compute_benchmark_tree_fingerprint,
    load_ledger_reference,
    load_record_manifest,
    load_suite_manifest,
    main,
    parse_raw_run,
    summarize_series,
    write_ledger_record,
)

BenchmarkValues = dict[tuple[str, str], float]
_REPO_ROOT = Path(__file__).parents[3]


def _suite_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "suite_id": "test-suite",
        "subject": "diwire",
        "libraries": ["diwire", "dishka", "wireup"],
        "scenarios": {
            "alpha": {
                "benchmark_file": "tests/benchmarks/test_alpha.py",
                "stable": True,
                "cells": {
                    "diwire": {"status": "subject"},
                    "dishka": {"status": "comparable"},
                    "wireup": {"status": "comparable"},
                },
            },
            "beta": {
                "benchmark_file": "tests/benchmarks/test_beta.py",
                "stable": True,
                "cells": {
                    "diwire": {"status": "subject"},
                    "dishka": {"status": "comparable"},
                    "wireup": {"status": "comparable"},
                },
            },
        },
    }


def _environment_payload() -> dict[str, object]:
    return {
        "python_executable": "/opt/cpython/bin/python3.14",
        "python_version": "3.14.6",
        "gil_mode": "enabled",
        "os": "Darwin 25.5.0",
        "architecture": "arm64",
        "cpu": "Apple M3 Pro",
        "power_state": "battery",
        "uv_lock_sha256": "abc123",
        "competitor_versions": {
            "dishka": "1.10.1",
            "pytest-benchmark": "5.2.3",
            "rodi": "2.1.0",
            "wireup": "2.12.0",
        },
    }


def _record_payload(
    *,
    raw_files: list[str],
    parent_record: str | None = None,
    original_record: str | None = None,
    evidence_files: list[str] | None = None,
) -> dict[str, object]:
    measurement_sets: list[dict[str, object]] = []
    if evidence_files is not None:
        measurement_sets.append(
            {
                "id": "focused",
                "role": "evidence",
                "command": "pytest focused",
                "raw_files": evidence_files,
            },
        )
    measurement_sets.append(
        {
            "id": "full",
            "role": "score",
            "command": "pytest full",
            "raw_files": raw_files,
        },
    )
    return {
        "schema_version": 1,
        "record_id": "record-one",
        "kind": "baseline",
        "revision": "abc123",
        "parent_record": parent_record,
        "original_record": original_record,
        "environment": _environment_payload(),
        "measurement_sets": measurement_sets,
        "hypothesis": "Measure the baseline",
        "conclusion": "Baseline recorded",
        "allocation_improvement_ratio": None,
    }


def _raw_payload(
    *,
    values: BenchmarkValues,
    commit: str = "abc123",
    dirty: bool = False,
    python_version: str = "3.14.6",
    run_marker: int = 1,
    benchmark_tree_sha256: str = "tree123",
) -> dict[str, object]:
    benchmarks: list[dict[str, object]] = []
    for (scenario, library), ops in values.items():
        mean = 1.0 / ops
        benchmarks.append(
            {
                "name": f"test_benchmark_{library}_{scenario}",
                "fullname": (
                    f"tests/benchmarks/test_{scenario}.py::test_benchmark_{library}_{scenario}"
                ),
                "options": {
                    "disable_gc": False,
                    "timer": "perf_counter",
                    "min_rounds": 5,
                },
                "stats": {
                    "min": mean * 0.98,
                    "max": mean * 1.02,
                    "mean": mean,
                    "stddev": mean * 0.01,
                    "rounds": 5,
                    "median": mean,
                    "ops": ops,
                    "iterations": 100,
                    "iqr_outliers": 0,
                    "stddev_outliers": 1,
                },
            },
        )
    return {
        "datetime": f"2026-07-18T10:00:0{run_marker}+00:00",
        "commit_info": {"id": commit, "dirty": dirty},
        "machine_info": {
            "python_version": python_version,
            "machine": "arm64",
            "cpu": {"brand_raw": "Apple M3 Pro"},
        },
        "diwire_benchmark_context": {
            **_environment_payload(),
            "python_version": python_version,
            "benchmark_tree_sha256": benchmark_tree_sha256,
        },
        "benchmarks": benchmarks,
    }


def _full_values(*, alpha_diwire: float = 110.0, beta_diwire: float = 200.0) -> BenchmarkValues:
    return {
        ("alpha", "diwire"): alpha_diwire,
        ("alpha", "dishka"): 100.0,
        ("alpha", "wireup"): 90.0,
        ("beta", "diwire"): beta_diwire,
        ("beta", "dishka"): 180.0,
        ("beta", "wireup"): 210.0,
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_fixture_files(
    tmp_path: Path,
    *,
    values_by_run: list[BenchmarkValues] | None = None,
    include_evidence: bool = False,
) -> tuple[Path, Path]:
    suite_path = tmp_path / "suite.json"
    _write_json(suite_path, _suite_payload())
    run_values = [_full_values()] * 3 if values_by_run is None else values_by_run
    raw_files: list[str] = []
    for index, values in enumerate(run_values, start=1):
        raw_path = tmp_path / f"full-{index}.json"
        _write_json(raw_path, _raw_payload(values=values, run_marker=index))
        raw_files.append(raw_path.name)
    evidence_files: list[str] | None = None
    if include_evidence:
        evidence_files = []
        evidence_values = {
            ("alpha", "diwire"): 111.0,
            ("alpha", "dishka"): 100.0,
        }
        for index in range(1, 3):
            evidence_path = tmp_path / f"focused-{index}.json"
            _write_json(
                evidence_path,
                _raw_payload(values=evidence_values, run_marker=index + 3),
            )
            evidence_files.append(evidence_path.name)
    manifest_path = tmp_path / "manifest.json"
    _write_json(
        manifest_path,
        _record_payload(raw_files=raw_files, evidence_files=evidence_files),
    )
    return suite_path, manifest_path


def _run(*, run_id: str, ops: float) -> IndependentRun:
    mean = 1.0 / ops
    return IndependentRun(
        run_id=run_id,
        source_path=f"{run_id}.json",
        datetime_utc="2026-07-18T10:00:00+00:00",
        benchmark_name="test_benchmark_diwire_alpha",
        benchmark_fullname="tests/benchmarks/test_alpha.py::test_benchmark_diwire_alpha",
        stats=RunStats(
            mean_seconds=mean,
            median_seconds=mean,
            min_seconds=mean,
            max_seconds=mean,
            stddev_seconds=0.0,
            rounds=5,
            iterations=100,
            mean_ops_per_second=ops,
            iqr_outliers=0,
            stddev_outliers=0,
        ),
    )


def test_build_ledger_uses_independent_run_medians_and_fastest_aggregate(
    tmp_path: Path,
) -> None:
    values_by_run = [
        _full_values(alpha_diwire=100.0),
        _full_values(alpha_diwire=120.0),
        _full_values(alpha_diwire=110.0),
    ]
    suite_path, manifest_path = _write_fixture_files(
        tmp_path,
        values_by_run=values_by_run,
        include_evidence=True,
    )
    suite = load_suite_manifest(suite_path)
    manifest = load_record_manifest(manifest_path)

    record = build_ledger_record(manifest, suite, parent=None, original=None)

    alpha = record.scenarios["alpha"]
    assert alpha.cells["diwire"] is not None
    assert alpha.cells["diwire"].headline_ops_per_second == 110.0
    assert alpha.fastest_competitor == "dishka"
    assert alpha.competitive_ratio == 1.10
    assert alpha.meets_margin
    beta = record.scenarios["beta"]
    assert beta.fastest_competitor == "wireup"
    assert beta.competitive_ratio == 200.0 / 210.0
    assert not beta.meets_margin
    assert record.score.misses_at_1_10 == 1
    assert record.score.minimum_competitive_ratio == 200.0 / 210.0
    assert record.score.worst_original_ratio == 1.0
    assert record.score.diwire_geometric_mean_ops_per_second == pytest.approx(
        math.sqrt(110.0 * 200.0),
    )
    assert len(record.measurement_sets) == 2
    assert record.measurement_sets[0].manifest.role == "evidence"
    assert set(record.measurement_sets[0].summaries) == {
        ("alpha", "diwire"),
        ("alpha", "dishka"),
    }


def test_committed_suite_policy_matches_benchmark_cells() -> None:
    suite = load_suite_manifest(_REPO_ROOT / "tools" / "performance_suite.json")
    benchmark_files = {
        str(path.relative_to(_REPO_ROOT))
        for path in (_REPO_ROOT / "tests" / "benchmarks").glob("test_*.py")
    }

    assert {policy.benchmark_file for policy in suite.scenarios.values()} == benchmark_files
    for scenario, policy in suite.scenarios.items():
        source = (_REPO_ROOT / policy.benchmark_file).read_text(encoding="utf-8")
        function_names = {
            node.name
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_benchmark_")
        }
        observed_libraries = {
            name.removeprefix("test_benchmark_").partition("_")[0] for name in function_names
        }
        expected_libraries = {
            library
            for library, cell in policy.cells.items()
            if cell.status.value in ("subject", "comparable")
        }
        assert observed_libraries == expected_libraries, scenario


def test_summarize_series_flags_outlier_without_removing_it() -> None:
    summary = summarize_series(
        [
            _run(run_id="one", ops=100.0),
            _run(run_id="two", ops=100.0),
            _run(run_id="outlier", ops=1000.0),
        ],
    )

    assert summary.headline_ops_per_second == 100.0
    assert summary.arithmetic_mean_ops_per_second == 400.0
    assert summary.sample_cv is not None
    assert summary.sample_cv > 1.0
    assert summary.outlier_run_ids == ("outlier",)
    assert len(summary.runs) == 3


def test_benchmark_tree_fingerprint_changes_with_inputs(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "package.py"
    benchmark_path = tmp_path / "tests" / "benchmarks" / "test_speed.py"
    conftest_path = tmp_path / "tests" / "conftest.py"
    source_path.parent.mkdir(parents=True)
    benchmark_path.parent.mkdir(parents=True)
    source_path.write_text("VALUE = 1\n", encoding="utf-8")
    benchmark_path.write_text("def test_speed(): ...\n", encoding="utf-8")
    conftest_path.write_text("\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    before = compute_benchmark_tree_fingerprint(tmp_path)
    source_path.write_text("VALUE = 2\n", encoding="utf-8")

    assert compute_benchmark_tree_fingerprint(tmp_path) != before


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (CompetitiveScore(0, 1.0, 1.0, 100.0, None), 1),
        (CompetitiveScore(2, 2.0, 2.0, 200.0, None), -1),
        (CompetitiveScore(1, 1.2, 1.0, 100.0, None), 1),
        (CompetitiveScore(1, 1.0, 1.1, 100.0, None), 1),
        (CompetitiveScore(1, 1.0, 1.0, 110.0, None), 1),
        (CompetitiveScore(1, 1.0, 1.0, 100.0, None), 0),
        (CompetitiveScore(1, 1.0, 1.0, 100.0, 1.1), 1),
        (CompetitiveScore(1, 1.0, 1.0, 100.0, 0.9), -1),
    ],
)
def test_compare_scores_is_lexicographic(
    candidate: CompetitiveScore,
    expected: int,
) -> None:
    reference = CompetitiveScore(1, 1.0, 1.0, 100.0, 1.0)

    assert compare_scores(candidate, reference) == expected


@pytest.mark.parametrize("mutation", ["missing_library", "unsupported_reason", "wrong_subject"])
def test_load_suite_manifest_rejects_invalid_cell_matrix(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = _suite_payload()
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, dict)
    alpha = scenarios["alpha"]
    assert isinstance(alpha, dict)
    cells = alpha["cells"]
    assert isinstance(cells, dict)
    if mutation == "missing_library":
        del cells["wireup"]
    elif mutation == "unsupported_reason":
        cells["wireup"] = {"status": "unsupported"}
    else:
        cells["diwire"] = {"status": "comparable"}
    suite_path = tmp_path / "suite.json"
    _write_json(suite_path, payload)

    with pytest.raises(PerformanceLedgerError):
        load_suite_manifest(suite_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            "missing",
            "Expected 'competitor_versions' to contain exactly the benchmark packages; "
            "missing=['rodi'], unexpected=[].",
        ),
        (
            "unexpected",
            "Expected 'competitor_versions' to contain exactly the benchmark packages; "
            "missing=[], unexpected=['extra-package'].",
        ),
    ],
)
def test_load_record_manifest_requires_exact_competitor_versions(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    payload = _record_payload(raw_files=["full.json"])
    environment = payload["environment"]
    assert isinstance(environment, dict)
    competitor_versions = environment["competitor_versions"]
    assert isinstance(competitor_versions, dict)
    if mutation == "missing":
        del competitor_versions["rodi"]
    else:
        competitor_versions["extra-package"] = "1.0.0"
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, payload)

    with pytest.raises(PerformanceLedgerError) as error:
        load_record_manifest(manifest_path)

    assert str(error.value) == message


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("ops", 0.0, "positive"),
        ("ops", "fast", "numeric"),
        ("ops", float("nan"), "finite"),
        ("ops", 999.0, "inconsistent"),
        ("rounds", 0, "positive"),
    ],
)
def test_parse_raw_run_rejects_invalid_stats(
    tmp_path: Path,
    key: str,
    value: object,
    message: str,
) -> None:
    suite_path = tmp_path / "suite.json"
    _write_json(suite_path, _suite_payload())
    suite = load_suite_manifest(suite_path)
    payload = _raw_payload(values={("alpha", "diwire"): 100.0})
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    stats = benchmarks[0]["stats"]
    assert isinstance(stats, dict)
    stats[key] = value
    raw_path = tmp_path / "raw.json"
    _write_json(raw_path, payload)

    with pytest.raises(PerformanceLedgerError, match=message):
        parse_raw_run(raw_path, suite)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("mean", 0.0097, "Benchmark mean must be within [min, max]."),
        ("mean", 0.0103, "Benchmark mean must be within [min, max]."),
        ("median", 0.0097, "Benchmark median must be within [min, max]."),
        ("median", 0.0103, "Benchmark median must be within [min, max]."),
        ("iqr_outliers", 6, "Benchmark iqr_outliers cannot exceed rounds."),
        ("stddev_outliers", 6, "Benchmark stddev_outliers cannot exceed rounds."),
    ],
)
def test_parse_raw_run_rejects_invalid_stat_relationships(
    tmp_path: Path,
    key: str,
    value: object,
    message: str,
) -> None:
    suite_path = tmp_path / "suite.json"
    _write_json(suite_path, _suite_payload())
    suite = load_suite_manifest(suite_path)
    payload = _raw_payload(values={("alpha", "diwire"): 100.0})
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    stats = benchmarks[0]["stats"]
    assert isinstance(stats, dict)
    stats[key] = value
    raw_path = tmp_path / "raw.json"
    _write_json(raw_path, payload)

    with pytest.raises(PerformanceLedgerError) as error:
        parse_raw_run(raw_path, suite)

    assert str(error.value) == message


def test_score_set_requires_every_comparable_cell(tmp_path: Path) -> None:
    values = _full_values()
    del values[("beta", "wireup")]
    suite_path, manifest_path = _write_fixture_files(
        tmp_path,
        values_by_run=[values, values, values],
    )

    with pytest.raises(PerformanceLedgerError, match="invalid matrix"):
        build_ledger_record(
            load_record_manifest(manifest_path),
            load_suite_manifest(suite_path),
            parent=None,
            original=None,
        )


def test_score_set_requires_three_unique_runs(tmp_path: Path) -> None:
    suite_path, manifest_path = _write_fixture_files(tmp_path)
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_payload["measurement_sets"][0]["raw_files"] = ["full-1.json"]
    _write_json(manifest_path, manifest_payload)

    with pytest.raises(PerformanceLedgerError, match="at least 3 independent runs"):
        build_ledger_record(
            load_record_manifest(manifest_path),
            load_suite_manifest(suite_path),
            parent=None,
            original=None,
        )


def test_score_set_rejects_copied_raw_artifacts(tmp_path: Path) -> None:
    suite_path, manifest_path = _write_fixture_files(tmp_path)
    first_raw_contents = (tmp_path / "full-1.json").read_text(encoding="utf-8")
    (tmp_path / "full-2.json").write_text(first_raw_contents, encoding="utf-8")

    with pytest.raises(PerformanceLedgerError, match="duplicate raw artifacts"):
        build_ledger_record(
            load_record_manifest(manifest_path),
            load_suite_manifest(suite_path),
            parent=None,
            original=None,
        )


def test_parse_raw_run_rejects_measurement_for_unsupported_cell(tmp_path: Path) -> None:
    suite_payload = _suite_payload()
    scenarios = suite_payload["scenarios"]
    assert isinstance(scenarios, dict)
    alpha = scenarios["alpha"]
    assert isinstance(alpha, dict)
    cells = alpha["cells"]
    assert isinstance(cells, dict)
    cells["wireup"] = {"status": "unsupported", "reason": "not supported"}
    suite_path = tmp_path / "suite.json"
    _write_json(suite_path, suite_payload)
    raw_path = tmp_path / "raw.json"
    _write_json(raw_path, _raw_payload(values={("alpha", "wireup"): 90.0}))

    with pytest.raises(PerformanceLedgerError, match="Unexpected measurement"):
        parse_raw_run(raw_path, load_suite_manifest(suite_path))


def test_record_rejects_mixed_python_versions(tmp_path: Path) -> None:
    suite_path, manifest_path = _write_fixture_files(tmp_path)
    second_raw_path = tmp_path / "full-2.json"
    _write_json(
        second_raw_path,
        _raw_payload(values=_full_values(), python_version="3.14.5"),
    )

    with pytest.raises(PerformanceLedgerError, match="mixes Python versions"):
        build_ledger_record(
            load_record_manifest(manifest_path),
            load_suite_manifest(suite_path),
            parent=None,
            original=None,
        )


def test_record_rejects_mixed_benchmark_input_trees(tmp_path: Path) -> None:
    suite_path, manifest_path = _write_fixture_files(tmp_path)
    second_raw_path = tmp_path / "full-2.json"
    _write_json(
        second_raw_path,
        _raw_payload(
            values=_full_values(),
            run_marker=2,
            benchmark_tree_sha256="different-tree",
        ),
    )

    with pytest.raises(PerformanceLedgerError, match="mixes benchmark input trees"):
        build_ledger_record(
            load_record_manifest(manifest_path),
            load_suite_manifest(suite_path),
            parent=None,
            original=None,
        )


def test_dirty_record_revision_is_bound_to_benchmark_tree(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.json"
    _write_json(suite_path, _suite_payload())
    raw_files: list[str] = []
    for index in range(1, 4):
        raw_path = tmp_path / f"dirty-{index}.json"
        _write_json(
            raw_path,
            _raw_payload(values=_full_values(), dirty=True, run_marker=index),
        )
        raw_files.append(raw_path.name)
    manifest_payload = _record_payload(raw_files=raw_files)
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest_payload)

    with pytest.raises(PerformanceLedgerError, match="does not match raw benchmark revision"):
        build_ledger_record(
            load_record_manifest(manifest_path),
            load_suite_manifest(suite_path),
            parent=None,
            original=None,
        )

    manifest_payload["revision"] = "abc123+dirty:tree123"
    _write_json(manifest_path, manifest_payload)
    record = build_ledger_record(
        load_record_manifest(manifest_path),
        load_suite_manifest(suite_path),
        parent=None,
        original=None,
    )
    assert record.manifest.revision == "abc123+dirty:tree123"


def test_main_writes_deterministic_record_and_applies_references(tmp_path: Path) -> None:
    suite_path, baseline_manifest_path = _write_fixture_files(tmp_path)
    baseline_output = tmp_path / "baseline.json"
    assert (
        main(
            [
                "--suite",
                str(suite_path),
                "--manifest",
                str(baseline_manifest_path),
                "--output",
                str(baseline_output),
            ],
        )
        == 0
    )
    first_output = baseline_output.read_text(encoding="utf-8")
    reference = load_ledger_reference(baseline_output)
    assert reference.subject_ops == {"alpha": 110.0, "beta": 200.0}

    candidate_values = _full_values(alpha_diwire=121.0, beta_diwire=190.0)
    candidate_files: list[str] = []
    for index in range(1, 4):
        raw_path = tmp_path / f"candidate-{index}.json"
        _write_json(
            raw_path,
            _raw_payload(values=candidate_values, commit="def456", run_marker=index),
        )
        candidate_files.append(raw_path.name)
    candidate_payload = _record_payload(
        raw_files=candidate_files,
        parent_record=baseline_output.name,
        original_record=baseline_output.name,
    )
    candidate_payload["record_id"] = "candidate"
    candidate_payload["kind"] = "candidate"
    candidate_payload["revision"] = "def456"
    candidate_manifest = tmp_path / "candidate-manifest.json"
    _write_json(candidate_manifest, candidate_payload)
    candidate_output = tmp_path / "candidate.json"

    assert (
        main(
            [
                "--suite",
                str(suite_path),
                "--manifest",
                str(candidate_manifest),
                "--output",
                str(candidate_output),
            ],
        )
        == 0
    )
    candidate_json = json.loads(candidate_output.read_text(encoding="utf-8"))
    assert candidate_json["worst_parent_ratio"] == 0.95
    assert candidate_json["score"]["worst_original_ratio"] == 0.95
    assert candidate_json["scenarios"]["alpha"]["parent_diwire_ratio"] == 1.1
    assert candidate_json["review_required"] is False
    assert candidate_json["scenarios"]["alpha"]["cells"]["diwire"]["reason"] is None
    assert first_output == baseline_output.read_text(encoding="utf-8")
    with pytest.raises(PerformanceLedgerError, match="already exists and is immutable"):
        main(
            [
                "--suite",
                str(suite_path),
                "--manifest",
                str(baseline_manifest_path),
                "--output",
                str(baseline_output),
            ],
        )
    assert first_output == baseline_output.read_text(encoding="utf-8")


def test_reference_environment_must_match(tmp_path: Path) -> None:
    suite_path, manifest_path = _write_fixture_files(tmp_path)
    suite = load_suite_manifest(suite_path)
    manifest = load_record_manifest(manifest_path)
    baseline = build_ledger_record(manifest, suite, parent=None, original=None)
    baseline_output = tmp_path / "baseline.json"
    write_ledger_record(baseline, baseline_output)
    reference = load_ledger_reference(baseline_output)
    mismatched = replace(
        reference,
        environment=replace(reference.environment, power_state="AC"),
    )

    with pytest.raises(PerformanceLedgerError, match="different environment"):
        build_ledger_record(
            manifest,
            suite,
            parent=mismatched,
            original=None,
        )
