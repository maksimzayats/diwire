from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, cast

BENCHMARK_LIBRARIES: Final[tuple[str, ...]] = ("diwire", "rodi", "dishka", "punq")
REQUIRED_BENCHMARK_LIBRARIES: Final[tuple[str, ...]] = ("diwire", "rodi", "dishka")
OPTIONAL_BENCHMARK_LIBRARIES: Final[tuple[str, ...]] = ("punq",)
_BENCHMARK_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^test_benchmark_(?P<library>[a-z0-9]+)_",
)


class BenchmarkReportError(ValueError):
    """Raised when benchmark output cannot be converted into the comparison report format."""


@dataclass(frozen=True)
class BenchmarkMetadata:
    """Metadata describing a benchmark run."""

    commit: str
    branch: str
    python_version: str
    datetime_utc: str
    source_raw_file: str


@dataclass(frozen=True)
class BenchmarkReport:
    """Normalized benchmark comparison data."""

    metadata: BenchmarkMetadata
    libraries: tuple[str, ...]
    scenarios: tuple[str, ...]
    files: dict[str, str]
    ops: dict[str, dict[str, float | None]]
    speedup_diwire_over_rodi: dict[str, float]
    speedup_diwire_over_dishka: dict[str, float]

    def as_json_dict(self) -> dict[str, object]:
        """Convert report into the normalized JSON artifact schema."""
        return {
            "metadata": {
                "commit": self.metadata.commit,
                "branch": self.metadata.branch,
                "python_version": self.metadata.python_version,
                "datetime_utc": self.metadata.datetime_utc,
                "source_raw_file": self.metadata.source_raw_file,
            },
            "libraries": list(self.libraries),
            "scenarios": list(self.scenarios),
            "files": self.files,
            "ops": _ops_to_json(ops_by_library=self.ops),
            "speedup_diwire_over_rodi": self.speedup_diwire_over_rodi,
            "speedup_diwire_over_dishka": self.speedup_diwire_over_dishka,
        }


def load_raw_benchmark_json(path: Path) -> dict[str, object]:
    """Load raw pytest-benchmark output from a JSON file."""
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = "Expected top-level JSON object in raw benchmark file."
        raise BenchmarkReportError(msg)
    return cast("dict[str, object]", loaded)


def normalize_benchmark_report(
    raw_payload: dict[str, object],
    *,
    source_raw_file: str,
) -> BenchmarkReport:
    """Normalize raw pytest-benchmark payload into a stable matrix format."""
    benchmark_entries = _read_benchmark_entries(raw_payload)
    files_by_scenario, raw_ops_by_library = _collect_benchmark_data(benchmark_entries)
    scenarios = tuple(sorted(files_by_scenario))
    if not scenarios:
        msg = "No benchmark results found in raw payload."
        raise BenchmarkReportError(msg)

    _validate_required_matrix(ops_by_library=raw_ops_by_library, scenarios=scenarios)

    speedup_over_rodi = _compute_speedup(
        ops_by_library=raw_ops_by_library,
        scenarios=scenarios,
        baseline_library="rodi",
    )
    speedup_over_dishka = _compute_speedup(
        ops_by_library=raw_ops_by_library,
        scenarios=scenarios,
        baseline_library="dishka",
    )
    metadata = _build_metadata(raw_payload=raw_payload, source_raw_file=source_raw_file)
    ops_by_library = _build_optional_matrix(
        raw_ops_by_library=raw_ops_by_library,
        scenarios=scenarios,
    )

    return BenchmarkReport(
        metadata=metadata,
        libraries=BENCHMARK_LIBRARIES,
        scenarios=scenarios,
        files=files_by_scenario,
        ops=ops_by_library,
        speedup_diwire_over_rodi=speedup_over_rodi,
        speedup_diwire_over_dishka=speedup_over_dishka,
    )


def render_benchmark_markdown(report: BenchmarkReport) -> str:
    """Render the benchmark matrix as Markdown."""
    lines = [
        "## Benchmark Results",
        "",
        f"- Commit: `{report.metadata.commit}`",
        f"- Branch: `{report.metadata.branch}`",
        f"- Python: `{report.metadata.python_version}`",
        f"- Datetime (UTC): `{report.metadata.datetime_utc}`",
        "",
        "| Scenario | diwire | rodi | dishka | punq | speedup diwire/rodi | speedup diwire/dishka |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for scenario in report.scenarios:
        diwire_ops = _format_ops(report.ops["diwire"][scenario])
        rodi_ops = _format_ops(report.ops["rodi"][scenario])
        dishka_ops = _format_ops(report.ops["dishka"][scenario])
        punq_ops = _format_ops(report.ops["punq"][scenario])
        speedup_over_rodi = f"{report.speedup_diwire_over_rodi[scenario]:.2f}x"
        speedup_over_dishka = f"{report.speedup_diwire_over_dishka[scenario]:.2f}x"
        lines.append(
            f"| {scenario} | {diwire_ops} | {rodi_ops} | {dishka_ops} | {punq_ops} "
            f"| {speedup_over_rodi} | {speedup_over_dishka} |",
        )
    return "\n".join(lines) + "\n"


def write_benchmark_outputs(
    report: BenchmarkReport,
    *,
    markdown_path: Path,
    json_path: Path,
    comment_path: Path,
) -> None:
    """Write Markdown and JSON benchmark report artifacts."""
    markdown = render_benchmark_markdown(report)
    json_text = json.dumps(report.as_json_dict(), indent=2, sort_keys=True) + "\n"

    for output_path in (markdown_path, json_path, comment_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)

    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json_text, encoding="utf-8")
    comment_path.write_text(markdown, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for benchmark report generation."""
    parser = argparse.ArgumentParser(description="Generate normalized benchmark report artifacts.")
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to raw pytest-benchmark JSON file.",
    )
    parser.add_argument(
        "--markdown",
        required=True,
        type=Path,
        help="Output path for Markdown table.",
    )
    parser.add_argument("--json", required=True, type=Path, help="Output path for normalized JSON.")
    parser.add_argument(
        "--comment",
        required=True,
        type=Path,
        help="Output path for PR comment body.",
    )
    args = parser.parse_args(argv)

    raw_payload = load_raw_benchmark_json(args.input)
    report = normalize_benchmark_report(raw_payload, source_raw_file=str(args.input))
    write_benchmark_outputs(
        report,
        markdown_path=args.markdown,
        json_path=args.json,
        comment_path=args.comment,
    )
    return 0


def _build_metadata(raw_payload: dict[str, object], *, source_raw_file: str) -> BenchmarkMetadata:
    commit_info = _read_optional_object(raw_payload, key="commit_info")
    machine_info = _read_optional_object(raw_payload, key="machine_info")

    commit = _read_optional_str(commit_info, key="id", default="unknown")
    branch = _read_optional_str(commit_info, key="branch", default="unknown")
    python_version = _read_optional_str(machine_info, key="python_version", default="unknown")
    datetime_raw = _read_optional_str(raw_payload, key="datetime", default="unknown")
    datetime_utc = _to_utc_isoformat(datetime_raw)

    return BenchmarkMetadata(
        commit=commit,
        branch=branch,
        python_version=python_version,
        datetime_utc=datetime_utc,
        source_raw_file=source_raw_file,
    )


def _read_benchmark_entries(raw_payload: dict[str, object]) -> list[dict[str, object]]:
    benchmarks_obj = raw_payload.get("benchmarks")
    if not isinstance(benchmarks_obj, list):
        msg = "Expected 'benchmarks' to be a list in raw benchmark payload."
        raise BenchmarkReportError(msg)

    entries: list[dict[str, object]] = []
    for benchmark_obj in benchmarks_obj:
        if not isinstance(benchmark_obj, dict):
            msg = "Each benchmark entry must be an object."
            raise BenchmarkReportError(msg)
        entries.append(cast("dict[str, object]", benchmark_obj))
    return entries


def _collect_benchmark_data(
    benchmark_entries: list[dict[str, object]],
) -> tuple[dict[str, str], dict[str, dict[str, float]]]:
    files_by_scenario: dict[str, str] = {}
    ops_by_library: dict[str, dict[str, float]] = {library: {} for library in BENCHMARK_LIBRARIES}

    for benchmark in benchmark_entries:
        name = _read_str(benchmark, key="name")
        full_name = _read_str(benchmark, key="fullname")
        stats = _read_object(benchmark, key="stats")
        ops = _read_float(stats, key="ops")
        library = _extract_library(name)
        benchmark_file = full_name.partition("::")[0]
        if not benchmark_file:
            msg = f"Invalid benchmark fullname '{full_name}'."
            raise BenchmarkReportError(msg)

        scenario = _scenario_name_from_file(benchmark_file)
        _store_scenario_file(
            files_by_scenario=files_by_scenario,
            scenario=scenario,
            benchmark_file=benchmark_file,
        )
        _store_ops(
            ops_by_library=ops_by_library,
            library=library,
            scenario=scenario,
            ops=ops,
        )

    return files_by_scenario, ops_by_library


def _store_scenario_file(
    *,
    files_by_scenario: dict[str, str],
    scenario: str,
    benchmark_file: str,
) -> None:
    existing_file = files_by_scenario.get(scenario)
    if existing_file is not None and existing_file != benchmark_file:
        msg = f"Scenario '{scenario}' is associated with multiple benchmark files."
        raise BenchmarkReportError(msg)
    files_by_scenario[scenario] = benchmark_file


def _store_ops(
    *,
    ops_by_library: dict[str, dict[str, float]],
    library: str,
    scenario: str,
    ops: float,
) -> None:
    if scenario in ops_by_library[library]:
        msg = f"Duplicate benchmark entry for library '{library}' in scenario '{scenario}'."
        raise BenchmarkReportError(msg)
    ops_by_library[library][scenario] = ops


def _validate_required_matrix(
    *,
    ops_by_library: dict[str, dict[str, float]],
    scenarios: tuple[str, ...],
) -> None:
    for scenario in scenarios:
        for library in REQUIRED_BENCHMARK_LIBRARIES:
            if scenario not in ops_by_library[library]:
                msg = f"Missing benchmark entry for library '{library}' in scenario '{scenario}'."
                raise BenchmarkReportError(msg)


def _build_optional_matrix(
    *,
    raw_ops_by_library: dict[str, dict[str, float]],
    scenarios: tuple[str, ...],
) -> dict[str, dict[str, float | None]]:
    normalized_ops_by_library: dict[str, dict[str, float | None]] = {}
    for library in REQUIRED_BENCHMARK_LIBRARIES:
        normalized_ops_by_library[library] = {
            scenario: raw_ops_by_library[library][scenario] for scenario in scenarios
        }
    for library in OPTIONAL_BENCHMARK_LIBRARIES:
        normalized_ops_by_library[library] = {
            scenario: raw_ops_by_library[library].get(scenario) for scenario in scenarios
        }
    return normalized_ops_by_library


def _compute_speedup(
    *,
    ops_by_library: dict[str, dict[str, float]],
    scenarios: tuple[str, ...],
    baseline_library: str,
) -> dict[str, float]:
    speedup: dict[str, float] = {}
    for scenario in scenarios:
        diwire_ops = ops_by_library["diwire"][scenario]
        baseline_ops = ops_by_library[baseline_library][scenario]
        if baseline_ops == 0:
            msg = (
                f"Cannot compute speedup for scenario '{scenario}' because "
                f"{baseline_library} OPS is zero."
            )
            raise BenchmarkReportError(msg)
        speedup[scenario] = diwire_ops / baseline_ops
    return speedup


def _extract_library(benchmark_name: str) -> str:
    match = _BENCHMARK_NAME_PATTERN.match(benchmark_name)
    if match is None:
        msg = f"Unexpected benchmark test name '{benchmark_name}'."
        raise BenchmarkReportError(msg)
    library = match.group("library")
    if library not in BENCHMARK_LIBRARIES:
        msg = f"Unexpected library '{library}' in benchmark test name '{benchmark_name}'."
        raise BenchmarkReportError(msg)
    return library


def _scenario_name_from_file(benchmark_file: str) -> str:
    stem = Path(benchmark_file).stem
    return stem.removeprefix("test_")


def _to_utc_isoformat(raw_datetime: str) -> str:
    if raw_datetime == "unknown":
        return raw_datetime
    normalized = raw_datetime.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return raw_datetime
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _read_object(container: dict[str, object], *, key: str) -> dict[str, object]:
    value = container.get(key)
    if not isinstance(value, dict):
        msg = f"Expected '{key}' to be an object."
        raise BenchmarkReportError(msg)
    return cast("dict[str, object]", value)


def _read_optional_object(container: dict[str, object], *, key: str) -> dict[str, object] | None:
    value = container.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        msg = f"Expected '{key}' to be an object when present."
        raise BenchmarkReportError(msg)
    return cast("dict[str, object]", value)


def _read_str(container: dict[str, object], *, key: str) -> str:
    value = container.get(key)
    if not isinstance(value, str):
        msg = f"Expected '{key}' to be a string."
        raise BenchmarkReportError(msg)
    return value


def _read_optional_str(
    container: dict[str, object] | None,
    *,
    key: str,
    default: str,
) -> str:
    if container is None:
        return default
    value = container.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        msg = f"Expected '{key}' to be a string when present."
        raise BenchmarkReportError(msg)
    return value


def _read_float(container: dict[str, object], *, key: str) -> float:
    value = container.get(key)
    if isinstance(value, int | float):
        return float(value)
    msg = f"Expected '{key}' to be a numeric value."
    raise BenchmarkReportError(msg)


def _format_ops(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}"


def _ops_to_json(
    *,
    ops_by_library: dict[str, dict[str, float | None]],
) -> dict[str, dict[str, float | str]]:
    return {
        library: {scenario: "-" if ops is None else ops for scenario, ops in scenario_ops.items()}
        for library, scenario_ops in ops_by_library.items()
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
