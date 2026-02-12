from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.benchmark_reporting import (
    BenchmarkReportError,
    load_raw_benchmark_json,
    main,
    normalize_benchmark_report,
    render_benchmark_markdown,
    write_benchmark_outputs,
)


def _raw_payload() -> dict[str, object]:
    return {
        "datetime": "2026-02-09T12:14:14+00:00",
        "commit_info": {
            "id": "abc123",
            "branch": "main",
        },
        "machine_info": {
            "python_version": "3.14.0",
        },
        "benchmarks": [
            {
                "name": "test_benchmark_diwire_resolve_transient",
                "fullname": (
                    "tests/benchmarks/test_resolve_transient.py"
                    "::test_benchmark_diwire_resolve_transient"
                ),
                "stats": {"ops": 500.0},
            },
            {
                "name": "test_benchmark_rodi_resolve_transient",
                "fullname": (
                    "tests/benchmarks/test_resolve_transient.py"
                    "::test_benchmark_rodi_resolve_transient"
                ),
                "stats": {"ops": 400.0},
            },
            {
                "name": "test_benchmark_dishka_resolve_transient",
                "fullname": (
                    "tests/benchmarks/test_resolve_transient.py"
                    "::test_benchmark_dishka_resolve_transient"
                ),
                "stats": {"ops": 250.0},
            },
            {
                "name": "test_benchmark_diwire_resolve_singleton",
                "fullname": (
                    "tests/benchmarks/test_resolve_singleton.py"
                    "::test_benchmark_diwire_resolve_singleton"
                ),
                "stats": {"ops": 1000.0},
            },
            {
                "name": "test_benchmark_rodi_resolve_singleton",
                "fullname": (
                    "tests/benchmarks/test_resolve_singleton.py"
                    "::test_benchmark_rodi_resolve_singleton"
                ),
                "stats": {"ops": 500.0},
            },
            {
                "name": "test_benchmark_dishka_resolve_singleton",
                "fullname": (
                    "tests/benchmarks/test_resolve_singleton.py"
                    "::test_benchmark_dishka_resolve_singleton"
                ),
                "stats": {"ops": 800.0},
            },
        ],
    }


def test_normalize_benchmark_report_builds_expected_matrix() -> None:
    report = normalize_benchmark_report(
        _raw_payload(),
        source_raw_file="benchmark-results/raw-benchmark.json",
    )

    assert report.libraries == ("diwire", "rodi", "dishka", "punq")
    assert report.scenarios == ("resolve_singleton", "resolve_transient")
    assert report.files == {
        "resolve_singleton": "tests/benchmarks/test_resolve_singleton.py",
        "resolve_transient": "tests/benchmarks/test_resolve_transient.py",
    }
    assert report.ops["diwire"] == {
        "resolve_singleton": 1000.0,
        "resolve_transient": 500.0,
    }
    assert report.ops["rodi"] == {
        "resolve_singleton": 500.0,
        "resolve_transient": 400.0,
    }
    assert report.ops["dishka"] == {
        "resolve_singleton": 800.0,
        "resolve_transient": 250.0,
    }
    assert report.ops["punq"] == {
        "resolve_singleton": None,
        "resolve_transient": None,
    }
    assert report.speedup_diwire_over_rodi == {
        "resolve_singleton": 2.0,
        "resolve_transient": 1.25,
    }
    assert report.speedup_diwire_over_dishka == {
        "resolve_singleton": 1.25,
        "resolve_transient": 2.0,
    }


def test_render_benchmark_markdown_renders_rows_and_metadata() -> None:
    report = normalize_benchmark_report(
        _raw_payload(),
        source_raw_file="benchmark-results/raw-benchmark.json",
    )

    markdown = render_benchmark_markdown(report)

    assert "## Benchmark Results" in markdown
    assert "- Commit: `abc123`" in markdown
    assert "- Python: `3.14.0`" in markdown
    assert (
        "| Scenario | diwire | rodi | dishka | punq | speedup diwire/rodi | "
        "speedup diwire/dishka |" in markdown
    )
    assert "| resolve_singleton | 1,000 | 500 | 800 | - | 2.00x | 1.25x |" in markdown
    assert "| resolve_transient | 500 | 400 | 250 | - | 1.25x | 2.00x |" in markdown


def test_normalize_benchmark_report_raises_for_missing_library_entry() -> None:
    payload = copy.deepcopy(_raw_payload())
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    payload["benchmarks"] = [
        entry for entry in benchmarks if "test_benchmark_dishka_resolve_transient" not in str(entry)
    ]

    with pytest.raises(BenchmarkReportError, match="Missing benchmark entry"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_for_duplicate_library_entry() -> None:
    payload = copy.deepcopy(_raw_payload())
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    benchmarks.append(
        {
            "name": "test_benchmark_diwire_resolve_singleton",
            "fullname": (
                "tests/benchmarks/test_resolve_singleton.py"
                "::test_benchmark_diwire_resolve_singleton_again"
            ),
            "stats": {"ops": 999.0},
        },
    )

    with pytest.raises(BenchmarkReportError, match="Duplicate benchmark entry"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_for_unexpected_library() -> None:
    payload = copy.deepcopy(_raw_payload())
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    benchmarks.append(
        {
            "name": "test_benchmark_injector_resolve_transient",
            "fullname": (
                "tests/benchmarks/test_resolve_transient.py"
                "::test_benchmark_injector_resolve_transient"
            ),
            "stats": {"ops": 777.0},
        },
    )

    with pytest.raises(BenchmarkReportError, match="Unexpected library"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_for_unexpected_benchmark_name() -> None:
    payload = copy.deepcopy(_raw_payload())
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    benchmarks[0]["name"] = "resolve_transient"

    with pytest.raises(BenchmarkReportError, match="Unexpected benchmark test name"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_for_zero_rodi_ops() -> None:
    payload = copy.deepcopy(_raw_payload())
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    for entry in benchmarks:
        if entry["name"] == "test_benchmark_rodi_resolve_singleton":
            entry["stats"]["ops"] = 0.0
            break

    with pytest.raises(BenchmarkReportError, match="rodi OPS is zero"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_for_zero_dishka_ops() -> None:
    payload = copy.deepcopy(_raw_payload())
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    for entry in benchmarks:
        if entry["name"] == "test_benchmark_dishka_resolve_singleton":
            entry["stats"]["ops"] = 0.0
            break

    with pytest.raises(BenchmarkReportError, match="dishka OPS is zero"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_for_no_benchmark_results() -> None:
    payload: dict[str, object] = {"benchmarks": []}

    with pytest.raises(BenchmarkReportError, match="No benchmark results found"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_when_benchmarks_is_not_a_list() -> None:
    payload: dict[str, object] = {"benchmarks": {}}

    with pytest.raises(BenchmarkReportError, match="Expected 'benchmarks' to be a list"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_when_benchmark_entry_is_not_an_object() -> None:
    payload: dict[str, object] = {"benchmarks": [1]}

    with pytest.raises(BenchmarkReportError, match="Each benchmark entry must be an object"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_for_invalid_benchmark_fullname() -> None:
    payload = copy.deepcopy(_raw_payload())
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    benchmarks[0]["fullname"] = "::broken"

    with pytest.raises(BenchmarkReportError, match="Invalid benchmark fullname"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_for_conflicting_files_in_same_scenario() -> None:
    payload = copy.deepcopy(_raw_payload())
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    for entry in benchmarks:
        if entry["name"] == "test_benchmark_rodi_resolve_singleton":
            entry["fullname"] = (
                "tests/alt/test_resolve_singleton.py::test_benchmark_rodi_resolve_singleton"
            )
            break

    with pytest.raises(BenchmarkReportError, match="associated with multiple benchmark files"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_when_benchmark_name_is_not_string() -> None:
    payload = copy.deepcopy(_raw_payload())
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    benchmarks[0]["name"] = 42

    with pytest.raises(BenchmarkReportError, match="Expected 'name' to be a string"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_when_stats_is_not_object() -> None:
    payload = copy.deepcopy(_raw_payload())
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    benchmarks[0]["stats"] = 1

    with pytest.raises(BenchmarkReportError, match="Expected 'stats' to be an object"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_when_ops_is_not_numeric() -> None:
    payload = copy.deepcopy(_raw_payload())
    benchmarks = payload["benchmarks"]
    assert isinstance(benchmarks, list)
    benchmarks[0]["stats"]["ops"] = "fast"

    with pytest.raises(BenchmarkReportError, match="Expected 'ops' to be a numeric value"):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_uses_unknown_metadata_defaults() -> None:
    payload = copy.deepcopy(_raw_payload())
    del payload["commit_info"]
    del payload["machine_info"]
    del payload["datetime"]

    report = normalize_benchmark_report(
        payload,
        source_raw_file="benchmark-results/raw-benchmark.json",
    )

    assert report.metadata.commit == "unknown"
    assert report.metadata.branch == "unknown"
    assert report.metadata.python_version == "unknown"
    assert report.metadata.datetime_utc == "unknown"


def test_normalize_benchmark_report_uses_default_when_optional_metadata_key_is_missing() -> None:
    payload = copy.deepcopy(_raw_payload())
    payload["commit_info"] = {}
    payload["machine_info"] = {}

    report = normalize_benchmark_report(
        payload,
        source_raw_file="benchmark-results/raw-benchmark.json",
    )

    assert report.metadata.commit == "unknown"
    assert report.metadata.branch == "unknown"
    assert report.metadata.python_version == "unknown"


def test_normalize_benchmark_report_raises_when_optional_object_has_wrong_type() -> None:
    payload = copy.deepcopy(_raw_payload())
    payload["commit_info"] = "bad"

    with pytest.raises(
        BenchmarkReportError,
        match="Expected 'commit_info' to be an object when present",
    ):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_raises_when_optional_string_has_wrong_type() -> None:
    payload = copy.deepcopy(_raw_payload())
    payload["datetime"] = 123

    with pytest.raises(
        BenchmarkReportError,
        match="Expected 'datetime' to be a string when present",
    ):
        normalize_benchmark_report(payload, source_raw_file="benchmark-results/raw-benchmark.json")


def test_normalize_benchmark_report_preserves_invalid_datetime_value() -> None:
    payload = copy.deepcopy(_raw_payload())
    payload["datetime"] = "not-a-date"

    report = normalize_benchmark_report(
        payload,
        source_raw_file="benchmark-results/raw-benchmark.json",
    )

    assert report.metadata.datetime_utc == "not-a-date"


def test_normalize_benchmark_report_normalizes_naive_datetime_to_utc() -> None:
    payload = copy.deepcopy(_raw_payload())
    payload["datetime"] = "2026-02-09T12:14:14"

    report = normalize_benchmark_report(
        payload,
        source_raw_file="benchmark-results/raw-benchmark.json",
    )

    assert report.metadata.datetime_utc == "2026-02-09T12:14:14+00:00"


def test_load_raw_benchmark_json_requires_top_level_object(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.json"
    raw_path.write_text("[]", encoding="utf-8")

    with pytest.raises(BenchmarkReportError, match="top-level JSON object"):
        load_raw_benchmark_json(raw_path)


def test_write_benchmark_outputs_writes_expected_files(tmp_path: Path) -> None:
    report = normalize_benchmark_report(
        _raw_payload(),
        source_raw_file="benchmark-results/raw-benchmark.json",
    )
    markdown_path = tmp_path / "benchmark-results" / "benchmark-table.md"
    json_path = tmp_path / "benchmark-results" / "benchmark-table.json"
    comment_path = tmp_path / "benchmark-results" / "pr-comment.md"

    write_benchmark_outputs(
        report,
        markdown_path=markdown_path,
        json_path=json_path,
        comment_path=comment_path,
    )

    assert markdown_path.exists()
    assert json_path.exists()
    assert comment_path.exists()
    assert comment_path.read_text(encoding="utf-8") == markdown_path.read_text(encoding="utf-8")

    report_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert report_json["metadata"]["commit"] == "abc123"
    assert report_json["libraries"] == ["diwire", "rodi", "dishka", "punq"]
    assert report_json["scenarios"] == ["resolve_singleton", "resolve_transient"]
    assert report_json["ops"]["punq"] == {"resolve_singleton": "-", "resolve_transient": "-"}
    assert report_json["speedup_diwire_over_rodi"]["resolve_singleton"] == 2.0
    assert report_json["speedup_diwire_over_dishka"]["resolve_singleton"] == 1.25


def test_main_generates_report_files(tmp_path: Path) -> None:
    input_path = tmp_path / "benchmark-results" / "raw-benchmark.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps(_raw_payload()), encoding="utf-8")

    markdown_path = tmp_path / "benchmark-results" / "benchmark-table.md"
    json_path = tmp_path / "benchmark-results" / "benchmark-table.json"
    comment_path = tmp_path / "benchmark-results" / "pr-comment.md"

    exit_code = main(
        [
            "--input",
            str(input_path),
            "--markdown",
            str(markdown_path),
            "--json",
            str(json_path),
            "--comment",
            str(comment_path),
        ],
    )

    assert exit_code == 0
    assert markdown_path.exists()
    assert json_path.exists()
    assert comment_path.exists()
