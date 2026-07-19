from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import statistics
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Final, cast

MARGIN_TARGET: Final = 1.10
MINIMUM_SCORE_RUNS: Final = 3
BENCHMARK_CONTEXT_KEY: Final = "diwire_benchmark_context"
_BENCHMARK_PACKAGES: Final[tuple[str, ...]] = (
    "dishka",
    "pytest-benchmark",
    "rodi",
    "wireup",
)
_BENCHMARK_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^test_benchmark_(?P<library>[a-z0-9]+)_",
)
_HIGH_CV_THRESHOLD: Final = 0.05
_MIN_OUTLIER_RUNS: Final = 3
_OUTLIER_MODIFIED_Z_THRESHOLD: Final = 3.5


class PerformanceLedgerError(ValueError):
    """Raised when benchmark evidence cannot produce a valid ledger record."""


class CellStatus(str, Enum):
    """Describe whether a library cell belongs in a comparison."""

    SUBJECT = "subject"
    COMPARABLE = "comparable"
    UNSUPPORTED = "unsupported"
    NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True)
class CellPolicy:
    """Comparison policy for one scenario and library."""

    status: CellStatus
    reason: str | None


@dataclass(frozen=True)
class ScenarioPolicy:
    """Stable benchmark scenario definition."""

    benchmark_file: str
    stable: bool
    cells: dict[str, CellPolicy]


@dataclass(frozen=True)
class SuitePolicy:
    """Versioned policy defining the benchmark comparison matrix."""

    schema_version: int
    suite_id: str
    suite_sha256: str
    subject: str
    libraries: tuple[str, ...]
    scenarios: dict[str, ScenarioPolicy]


@dataclass(frozen=True)
class BenchmarkEnvironment:
    """Environment metadata absent from pytest-benchmark raw output."""

    python_executable: str
    python_version: str
    gil_mode: str
    os: str
    architecture: str
    cpu: str
    power_state: str
    uv_lock_sha256: str
    competitor_versions: dict[str, str]


@dataclass(frozen=True)
class MeasurementSetManifest:
    """Raw files and command for one independent measurement set."""

    measurement_id: str
    role: str
    command: str
    raw_files: tuple[Path, ...]


@dataclass(frozen=True)
class RecordManifest:
    """User-supplied metadata for one ledger record."""

    schema_version: int
    record_id: str
    kind: str
    revision: str
    parent_record: Path | None
    original_record: Path | None
    environment: BenchmarkEnvironment
    measurement_sets: tuple[MeasurementSetManifest, ...]
    hypothesis: str
    conclusion: str
    allocation_improvement_ratio: float | None


@dataclass(frozen=True)
class RunStats:
    """Retained pytest-benchmark statistics for one independent run."""

    mean_seconds: float
    median_seconds: float
    min_seconds: float
    max_seconds: float
    stddev_seconds: float
    rounds: int
    iterations: int
    mean_ops_per_second: float
    iqr_outliers: int
    stddev_outliers: int


@dataclass(frozen=True)
class IndependentRun:
    """One scenario/library observation from a raw benchmark artifact."""

    run_id: str
    source_path: str
    datetime_utc: str
    benchmark_name: str
    benchmark_fullname: str
    stats: RunStats


@dataclass(frozen=True)
class RawRun:
    """Validated observations and metadata from one raw JSON file."""

    source_path: str
    raw_sha256: str
    commit: str
    dirty: bool
    python_version: str
    benchmark_tree_sha256: str
    environment: BenchmarkEnvironment
    machine_fingerprint: str
    options_fingerprint: str
    cells: dict[tuple[str, str], IndependentRun]


@dataclass(frozen=True)
class SeriesSummary:
    """Aggregate several independent mean-throughput observations."""

    runs: tuple[IndependentRun, ...]
    headline_ops_per_second: float
    arithmetic_mean_ops_per_second: float
    sample_cv: float | None
    outlier_run_ids: tuple[str, ...]


@dataclass(frozen=True)
class MeasurementSetRecord:
    """Validated raw runs and aggregates for one measurement role."""

    manifest: MeasurementSetManifest
    raw_runs: tuple[RawRun, ...]
    summaries: dict[tuple[str, str], SeriesSummary]


@dataclass(frozen=True)
class ScenarioResult:
    """Competitive and regression result for one stable scenario."""

    cells: dict[str, SeriesSummary | None]
    fastest_competitor: str
    fastest_competitor_ops_per_second: float
    competitive_ratio: float
    meets_margin: bool
    parent_diwire_ratio: float
    original_diwire_ratio: float


@dataclass(frozen=True)
class CompetitiveScore:
    """Lexicographic performance score defined by the optimization goal."""

    misses_at_1_10: int
    minimum_competitive_ratio: float
    worst_original_ratio: float
    diwire_geometric_mean_ops_per_second: float
    allocation_improvement_ratio: float | None


@dataclass(frozen=True)
class LedgerReference:
    """Comparable values loaded from an earlier immutable ledger record."""

    record_id: str
    suite_sha256: str
    environment: BenchmarkEnvironment
    subject_ops: dict[str, float]


@dataclass(frozen=True)
class LedgerRecord:
    """Complete reproducible performance record."""

    manifest: RecordManifest
    suite: SuitePolicy
    measurement_sets: tuple[MeasurementSetRecord, ...]
    scenarios: dict[str, ScenarioResult]
    score: CompetitiveScore
    worst_parent_ratio: float
    quality_warnings: tuple[str, ...]


def load_suite_manifest(path: Path) -> SuitePolicy:
    """Load and validate the versioned benchmark comparison policy."""
    payload = _load_json_object(path)
    schema_version = _read_int(payload, key="schema_version")
    if schema_version != 1:
        msg = f"Unsupported suite schema version {schema_version}."
        raise PerformanceLedgerError(msg)

    suite_id = _read_non_empty_str(payload, key="suite_id")
    subject = _read_non_empty_str(payload, key="subject")
    libraries = _read_unique_str_tuple(payload, key="libraries")
    if subject not in libraries:
        msg = f"Suite subject '{subject}' is not present in libraries."
        raise PerformanceLedgerError(msg)

    scenarios_payload = _read_object(payload, key="scenarios")
    scenarios: dict[str, ScenarioPolicy] = {}
    benchmark_files: set[str] = set()
    for scenario, scenario_value in scenarios_payload.items():
        if not isinstance(scenario_value, dict):
            msg = f"Scenario '{scenario}' must be an object."
            raise PerformanceLedgerError(msg)
        scenario_payload = cast("dict[str, object]", scenario_value)
        benchmark_file = _read_non_empty_str(scenario_payload, key="benchmark_file")
        if benchmark_file in benchmark_files:
            msg = f"Benchmark file '{benchmark_file}' is assigned to multiple scenarios."
            raise PerformanceLedgerError(msg)
        benchmark_files.add(benchmark_file)
        stable = _read_bool(scenario_payload, key="stable")
        cells_payload = _read_object(scenario_payload, key="cells")
        if set(cells_payload) != set(libraries):
            msg = f"Scenario '{scenario}' must define exactly one policy for every library."
            raise PerformanceLedgerError(msg)
        cells = {
            library: _parse_cell_policy(
                scenario=scenario,
                library=library,
                value=cells_payload[library],
            )
            for library in libraries
        }
        if cells[subject].status is not CellStatus.SUBJECT:
            msg = f"Scenario '{scenario}' must mark '{subject}' as the subject."
            raise PerformanceLedgerError(msg)
        comparable_count = sum(cell.status is CellStatus.COMPARABLE for cell in cells.values())
        if stable and comparable_count == 0:
            msg = f"Stable scenario '{scenario}' has no comparable competitor."
            raise PerformanceLedgerError(msg)
        scenarios[scenario] = ScenarioPolicy(
            benchmark_file=benchmark_file,
            stable=stable,
            cells=cells,
        )

    if not scenarios:
        msg = "Suite manifest must define at least one scenario."
        raise PerformanceLedgerError(msg)
    return SuitePolicy(
        schema_version=schema_version,
        suite_id=suite_id,
        suite_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        subject=subject,
        libraries=libraries,
        scenarios=scenarios,
    )


def load_record_manifest(path: Path) -> RecordManifest:
    """Load metadata and raw artifact paths for one experiment."""
    payload = _load_json_object(path)
    schema_version = _read_int(payload, key="schema_version")
    if schema_version != 1:
        msg = f"Unsupported record schema version {schema_version}."
        raise PerformanceLedgerError(msg)
    measurement_payloads = _read_list(payload, key="measurement_sets")
    measurement_sets = tuple(
        _parse_measurement_set(value=value, manifest_directory=path.parent)
        for value in measurement_payloads
    )
    score_sets = [measurement for measurement in measurement_sets if measurement.role == "score"]
    if len(score_sets) != 1:
        msg = "Record manifest must define exactly one measurement set with role 'score'."
        raise PerformanceLedgerError(msg)

    allocation_ratio = _read_optional_float(payload, key="allocation_improvement_ratio")
    if allocation_ratio is not None and allocation_ratio <= 0:
        msg = "Allocation improvement ratio must be positive when present."
        raise PerformanceLedgerError(msg)
    return RecordManifest(
        schema_version=schema_version,
        record_id=_read_non_empty_str(payload, key="record_id"),
        kind=_read_non_empty_str(payload, key="kind"),
        revision=_read_non_empty_str(payload, key="revision"),
        parent_record=_read_optional_path(payload, key="parent_record", parent=path.parent),
        original_record=_read_optional_path(payload, key="original_record", parent=path.parent),
        environment=_parse_environment(_read_object(payload, key="environment")),
        measurement_sets=measurement_sets,
        hypothesis=_read_non_empty_str(payload, key="hypothesis"),
        conclusion=_read_non_empty_str(payload, key="conclusion"),
        allocation_improvement_ratio=allocation_ratio,
    )


def compute_benchmark_tree_fingerprint(repo_root: Path) -> str:
    """Hash every source and configuration file that can affect benchmark execution."""
    input_files = [
        *sorted((repo_root / "src").rglob("*.py")),
        *sorted((repo_root / "tests" / "benchmarks").rglob("*.py")),
        repo_root / "pyproject.toml",
        repo_root / "uv.lock",
    ]
    optional_inputs = (
        repo_root / ".python-version",
        repo_root / "tests" / "conftest.py",
    )
    input_files.extend(path for path in optional_inputs if path.exists())
    missing = [path for path in input_files if not path.is_file()]
    if missing:
        msg = f"Cannot fingerprint missing benchmark inputs: {missing}."
        raise PerformanceLedgerError(msg)

    digest = hashlib.sha256()
    for path in sorted(input_files):
        relative_path = path.relative_to(repo_root).as_posix().encode()
        contents = path.read_bytes()
        digest.update(len(relative_path).to_bytes(8, byteorder="big"))
        digest.update(relative_path)
        digest.update(len(contents).to_bytes(8, byteorder="big"))
        digest.update(contents)
    return digest.hexdigest()


def build_benchmark_context(
    *,
    repo_root: Path,
    machine_info: Mapping[str, object],
) -> dict[str, object]:
    """Build metadata embedded into raw benchmark JSON after measurements finish."""
    cpu_info = _read_object(machine_info, key="cpu")
    power_state = os.environ.get("DIWIRE_BENCHMARK_POWER_STATE", "unrecorded")
    if not power_state:
        msg = "DIWIRE_BENCHMARK_POWER_STATE must be non-empty when set."
        raise PerformanceLedgerError(msg)
    system = _read_non_empty_str(machine_info, key="system")
    release = _read_non_empty_str(machine_info, key="release")
    gil_enabled = getattr(sys, "_is_gil_enabled", lambda: True)()
    return {
        "benchmark_tree_sha256": compute_benchmark_tree_fingerprint(repo_root),
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": _read_non_empty_str(machine_info, key="python_version"),
        "gil_mode": "enabled" if gil_enabled else "disabled",
        "os": f"{system} {release}",
        "architecture": _read_non_empty_str(machine_info, key="machine"),
        "cpu": _read_non_empty_str(cpu_info, key="brand_raw"),
        "power_state": power_state,
        "uv_lock_sha256": hashlib.sha256((repo_root / "uv.lock").read_bytes()).hexdigest(),
        "competitor_versions": {
            package: importlib.metadata.version(package) for package in _BENCHMARK_PACKAGES
        },
    }


def parse_raw_run(path: Path, suite: SuitePolicy) -> RawRun:
    """Parse one raw pytest-benchmark JSON artifact."""
    payload = _load_json_object(path)
    benchmark_payloads = _read_list(payload, key="benchmarks")
    if not benchmark_payloads:
        msg = f"Raw benchmark file '{path}' contains no benchmark entries."
        raise PerformanceLedgerError(msg)

    benchmark_file_to_scenario = {
        policy.benchmark_file: scenario for scenario, policy in suite.scenarios.items()
    }
    cells: dict[tuple[str, str], IndependentRun] = {}
    option_fingerprints: set[str] = set()
    datetime_utc = _read_non_empty_str(payload, key="datetime")
    for benchmark_value in benchmark_payloads:
        benchmark = _cast_object(benchmark_value, label="benchmark entry")
        name = _read_non_empty_str(benchmark, key="name")
        fullname = _read_non_empty_str(benchmark, key="fullname")
        library = _extract_library(name=name, libraries=suite.libraries)
        benchmark_file = fullname.partition("::")[0]
        scenario = benchmark_file_to_scenario.get(benchmark_file)
        if scenario is None:
            msg = f"Unexpected benchmark file '{benchmark_file}' in '{path}'."
            raise PerformanceLedgerError(msg)
        policy = suite.scenarios[scenario].cells[library]
        if policy.status not in (CellStatus.SUBJECT, CellStatus.COMPARABLE):
            msg = (
                f"Unexpected measurement for {library}/{scenario}; suite status is "
                f"'{policy.status.value}'."
            )
            raise PerformanceLedgerError(msg)
        key = (scenario, library)
        if key in cells:
            msg = f"Duplicate benchmark entry for {library}/{scenario} in '{path}'."
            raise PerformanceLedgerError(msg)
        options = _read_object(benchmark, key="options")
        option_fingerprints.add(_canonical_json(options))
        cells[key] = IndependentRun(
            run_id=path.stem,
            source_path=str(path),
            datetime_utc=datetime_utc,
            benchmark_name=name,
            benchmark_fullname=fullname,
            stats=_parse_stats(_read_object(benchmark, key="stats")),
        )

    if len(option_fingerprints) != 1:
        msg = f"Raw benchmark file '{path}' mixes benchmark option sets."
        raise PerformanceLedgerError(msg)
    commit_info = _read_object(payload, key="commit_info")
    machine_info = _read_object(payload, key="machine_info")
    benchmark_context = _read_object(payload, key=BENCHMARK_CONTEXT_KEY)
    return RawRun(
        source_path=str(path),
        raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        commit=_read_non_empty_str(commit_info, key="id"),
        dirty=_read_bool(commit_info, key="dirty"),
        python_version=_read_non_empty_str(machine_info, key="python_version"),
        benchmark_tree_sha256=_read_non_empty_str(
            benchmark_context,
            key="benchmark_tree_sha256",
        ),
        environment=_parse_environment(benchmark_context),
        machine_fingerprint=_canonical_json(machine_info),
        options_fingerprint=option_fingerprints.pop(),
        cells=cells,
    )


def summarize_series(runs: Sequence[IndependentRun]) -> SeriesSummary:
    """Summarize independent mean-throughput observations without dropping outliers."""
    if not runs:
        msg = "Cannot summarize an empty benchmark series."
        raise PerformanceLedgerError(msg)
    ops = [run.stats.mean_ops_per_second for run in runs]
    arithmetic_mean = statistics.fmean(ops)
    sample_cv = None
    if len(ops) > 1:
        sample_cv = statistics.stdev(ops) / arithmetic_mean
    return SeriesSummary(
        runs=tuple(runs),
        headline_ops_per_second=statistics.median(ops),
        arithmetic_mean_ops_per_second=arithmetic_mean,
        sample_cv=sample_cv,
        outlier_run_ids=_find_outlier_run_ids(runs),
    )


def build_ledger_record(
    manifest: RecordManifest,
    suite: SuitePolicy,
    *,
    parent: LedgerReference | None,
    original: LedgerReference | None,
) -> LedgerRecord:
    """Build a validated immutable ledger record from raw artifacts."""
    measurement_sets = tuple(
        _build_measurement_set(measurement=measurement, suite=suite)
        for measurement in manifest.measurement_sets
    )
    _validate_measurement_metadata(
        measurement_sets=measurement_sets,
        environment=manifest.environment,
        revision=manifest.revision,
    )
    _validate_reference(reference=parent, suite=suite, environment=manifest.environment)
    _validate_reference(reference=original, suite=suite, environment=manifest.environment)

    score_set = next(
        measurement for measurement in measurement_sets if measurement.manifest.role == "score"
    )
    scenarios = _build_scenario_results(
        score_set=score_set,
        suite=suite,
        parent=parent,
        original=original,
    )
    competitive_ratios = [result.competitive_ratio for result in scenarios.values()]
    subject_headlines = [
        _require_summary(result.cells[suite.subject]).headline_ops_per_second
        for result in scenarios.values()
    ]
    score = CompetitiveScore(
        misses_at_1_10=sum(not result.meets_margin for result in scenarios.values()),
        minimum_competitive_ratio=min(competitive_ratios),
        worst_original_ratio=min(result.original_diwire_ratio for result in scenarios.values()),
        diwire_geometric_mean_ops_per_second=_geometric_mean(subject_headlines),
        allocation_improvement_ratio=manifest.allocation_improvement_ratio,
    )
    warnings = _quality_warnings(measurement_sets)
    return LedgerRecord(
        manifest=manifest,
        suite=suite,
        measurement_sets=measurement_sets,
        scenarios=scenarios,
        score=score,
        worst_parent_ratio=min(result.parent_diwire_ratio for result in scenarios.values()),
        quality_warnings=warnings,
    )


def compare_scores(candidate: CompetitiveScore, reference: CompetitiveScore) -> int:
    """Return one when candidate wins lexicographically, zero for equality, else minus one."""
    dimensions = (
        (reference.misses_at_1_10, candidate.misses_at_1_10),
        (candidate.minimum_competitive_ratio, reference.minimum_competitive_ratio),
        (candidate.worst_original_ratio, reference.worst_original_ratio),
        (
            candidate.diwire_geometric_mean_ops_per_second,
            reference.diwire_geometric_mean_ops_per_second,
        ),
    )
    for candidate_value, reference_value in dimensions:
        if candidate_value > reference_value:
            return 1
        if candidate_value < reference_value:
            return -1
    if (
        candidate.allocation_improvement_ratio is not None
        and reference.allocation_improvement_ratio is not None
    ):
        if candidate.allocation_improvement_ratio > reference.allocation_improvement_ratio:
            return 1
        if candidate.allocation_improvement_ratio < reference.allocation_improvement_ratio:
            return -1
    return 0


def load_ledger_reference(path: Path) -> LedgerReference:
    """Load the comparable subset of a previously generated ledger record."""
    payload = _load_json_object(path)
    suite_payload = _read_object(payload, key="suite")
    manifest_payload = _read_object(payload, key="manifest")
    scenarios_payload = _read_object(payload, key="scenarios")
    subject = _read_non_empty_str(suite_payload, key="subject")
    subject_ops: dict[str, float] = {}
    for scenario, scenario_value in scenarios_payload.items():
        scenario_payload = _cast_object(scenario_value, label=f"scenario '{scenario}'")
        cells = _read_object(scenario_payload, key="cells")
        subject_cell = _read_object(cells, key=subject)
        summary = _read_object(subject_cell, key="summary")
        subject_ops[scenario] = _read_float(summary, key="headline_ops_per_second")
    return LedgerReference(
        record_id=_read_non_empty_str(manifest_payload, key="record_id"),
        suite_sha256=_read_non_empty_str(suite_payload, key="suite_sha256"),
        environment=_parse_environment(_read_object(manifest_payload, key="environment")),
        subject_ops=subject_ops,
    )


def write_ledger_record(record: LedgerRecord, path: Path) -> None:
    """Write one deterministic, machine-readable performance record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _ledger_record_as_json(record)
    serialized = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8") as output_file:
            output_file.write(serialized)
    except FileExistsError as error:
        msg = f"Ledger record '{path}' already exists and is immutable."
        raise PerformanceLedgerError(msg) from error


def main(argv: list[str] | None = None) -> int:
    """Generate one immutable performance ledger record."""
    parser = argparse.ArgumentParser(description="Build a multi-run DIWire performance record.")
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    suite = load_suite_manifest(args.suite)
    manifest = load_record_manifest(args.manifest)
    parent = (
        None if manifest.parent_record is None else load_ledger_reference(manifest.parent_record)
    )
    original = (
        None
        if manifest.original_record is None
        else load_ledger_reference(manifest.original_record)
    )
    record = build_ledger_record(
        manifest,
        suite,
        parent=parent,
        original=original,
    )
    write_ledger_record(record, args.output)
    return 0


def _parse_cell_policy(*, scenario: str, library: str, value: object) -> CellPolicy:
    payload = _cast_object(value, label=f"cell policy for {library}/{scenario}")
    status_raw = _read_non_empty_str(payload, key="status")
    try:
        status = CellStatus(status_raw)
    except ValueError as error:
        msg = f"Unknown cell status '{status_raw}' for {library}/{scenario}."
        raise PerformanceLedgerError(msg) from error
    reason = _read_optional_str(payload, key="reason")
    if status in (CellStatus.UNSUPPORTED, CellStatus.NOT_COMPARABLE) and not reason:
        msg = f"Cell {library}/{scenario} with status '{status.value}' requires a reason."
        raise PerformanceLedgerError(msg)
    if status in (CellStatus.SUBJECT, CellStatus.COMPARABLE) and reason is not None:
        msg = f"Measured cell {library}/{scenario} must not define an unsupported reason."
        raise PerformanceLedgerError(msg)
    return CellPolicy(status=status, reason=reason)


def _parse_environment(payload: dict[str, object]) -> BenchmarkEnvironment:
    competitor_versions = _read_str_mapping(payload, key="competitor_versions")
    expected_packages = set(_BENCHMARK_PACKAGES)
    actual_packages = set(competitor_versions)
    if actual_packages != expected_packages:
        missing = sorted(expected_packages - actual_packages)
        unexpected = sorted(actual_packages - expected_packages)
        msg = (
            "Expected 'competitor_versions' to contain exactly the benchmark packages; "
            f"missing={missing}, unexpected={unexpected}."
        )
        raise PerformanceLedgerError(msg)
    return BenchmarkEnvironment(
        python_executable=_read_non_empty_str(payload, key="python_executable"),
        python_version=_read_non_empty_str(payload, key="python_version"),
        gil_mode=_read_non_empty_str(payload, key="gil_mode"),
        os=_read_non_empty_str(payload, key="os"),
        architecture=_read_non_empty_str(payload, key="architecture"),
        cpu=_read_non_empty_str(payload, key="cpu"),
        power_state=_read_non_empty_str(payload, key="power_state"),
        uv_lock_sha256=_read_non_empty_str(payload, key="uv_lock_sha256"),
        competitor_versions=competitor_versions,
    )


def _parse_measurement_set(
    *,
    value: object,
    manifest_directory: Path,
) -> MeasurementSetManifest:
    payload = _cast_object(value, label="measurement set")
    role = _read_non_empty_str(payload, key="role")
    if role not in ("evidence", "score"):
        msg = f"Unknown measurement set role '{role}'."
        raise PerformanceLedgerError(msg)
    raw_files = tuple(
        manifest_directory / raw_file
        for raw_file in _read_unique_str_tuple(payload, key="raw_files")
    )
    return MeasurementSetManifest(
        measurement_id=_read_non_empty_str(payload, key="id"),
        role=role,
        command=_read_non_empty_str(payload, key="command"),
        raw_files=raw_files,
    )


def _parse_stats(payload: dict[str, object]) -> RunStats:
    stats = RunStats(
        mean_seconds=_read_positive_float(payload, key="mean"),
        median_seconds=_read_positive_float(payload, key="median"),
        min_seconds=_read_positive_float(payload, key="min"),
        max_seconds=_read_positive_float(payload, key="max"),
        stddev_seconds=_read_non_negative_float(payload, key="stddev"),
        rounds=_read_positive_int(payload, key="rounds"),
        iterations=_read_positive_int(payload, key="iterations"),
        mean_ops_per_second=_read_positive_float(payload, key="ops"),
        iqr_outliers=_read_non_negative_int(payload, key="iqr_outliers"),
        stddev_outliers=_read_non_negative_int(payload, key="stddev_outliers"),
    )
    if not stats.min_seconds <= stats.mean_seconds <= stats.max_seconds:
        msg = "Benchmark mean must be within [min, max]."
        raise PerformanceLedgerError(msg)
    if not stats.min_seconds <= stats.median_seconds <= stats.max_seconds:
        msg = "Benchmark median must be within [min, max]."
        raise PerformanceLedgerError(msg)
    if stats.iqr_outliers > stats.rounds:
        msg = "Benchmark iqr_outliers cannot exceed rounds."
        raise PerformanceLedgerError(msg)
    if stats.stddev_outliers > stats.rounds:
        msg = "Benchmark stddev_outliers cannot exceed rounds."
        raise PerformanceLedgerError(msg)
    expected_ops = 1.0 / stats.mean_seconds
    if not math.isclose(stats.mean_ops_per_second, expected_ops, rel_tol=1e-9):
        msg = "Benchmark OPS is inconsistent with reciprocal mean duration."
        raise PerformanceLedgerError(msg)
    return stats


def _build_measurement_set(
    *,
    measurement: MeasurementSetManifest,
    suite: SuitePolicy,
) -> MeasurementSetRecord:
    raw_runs = tuple(parse_raw_run(path, suite) for path in measurement.raw_files)
    if not raw_runs:
        msg = f"Measurement set '{measurement.measurement_id}' has no raw runs."
        raise PerformanceLedgerError(msg)
    if measurement.role == "score" and len(raw_runs) < MINIMUM_SCORE_RUNS:
        msg = (
            f"Score measurement set '{measurement.measurement_id}' requires at least "
            f"{MINIMUM_SCORE_RUNS} independent runs."
        )
        raise PerformanceLedgerError(msg)
    raw_hashes = {raw_run.raw_sha256 for raw_run in raw_runs}
    if len(raw_hashes) != len(raw_runs):
        msg = f"Measurement set '{measurement.measurement_id}' contains duplicate raw artifacts."
        raise PerformanceLedgerError(msg)
    expected_cells = set(raw_runs[0].cells)
    for raw_run in raw_runs[1:]:
        if set(raw_run.cells) != expected_cells:
            msg = f"Measurement set '{measurement.measurement_id}' mixes benchmark matrices."
            raise PerformanceLedgerError(msg)
    if measurement.role == "score":
        required_cells = {
            (scenario, library)
            for scenario, scenario_policy in suite.scenarios.items()
            if scenario_policy.stable
            for library, cell in scenario_policy.cells.items()
            if cell.status in (CellStatus.SUBJECT, CellStatus.COMPARABLE)
        }
        if expected_cells != required_cells:
            missing = sorted(required_cells - expected_cells)
            unexpected = sorted(expected_cells - required_cells)
            msg = (
                f"Score measurement set '{measurement.measurement_id}' has an invalid matrix; "
                f"missing={missing}, unexpected={unexpected}."
            )
            raise PerformanceLedgerError(msg)
    summaries = {
        key: summarize_series([raw_run.cells[key] for raw_run in raw_runs])
        for key in sorted(expected_cells)
    }
    return MeasurementSetRecord(
        manifest=measurement,
        raw_runs=raw_runs,
        summaries=summaries,
    )


def _validate_measurement_metadata(
    *,
    measurement_sets: Sequence[MeasurementSetRecord],
    environment: BenchmarkEnvironment,
    revision: str,
) -> None:
    raw_runs = [raw_run for measurement in measurement_sets for raw_run in measurement.raw_runs]
    first = raw_runs[0]
    for raw_run in raw_runs[1:]:
        if raw_run.commit != first.commit or raw_run.dirty != first.dirty:
            msg = "Measurement record mixes commits or dirty states."
            raise PerformanceLedgerError(msg)
        if raw_run.python_version != first.python_version:
            msg = "Measurement record mixes Python versions."
            raise PerformanceLedgerError(msg)
        if raw_run.benchmark_tree_sha256 != first.benchmark_tree_sha256:
            msg = "Measurement record mixes benchmark input trees."
            raise PerformanceLedgerError(msg)
        if raw_run.environment != first.environment:
            msg = "Measurement record mixes benchmark environments."
            raise PerformanceLedgerError(msg)
        if raw_run.machine_fingerprint != first.machine_fingerprint:
            msg = "Measurement record mixes machines."
            raise PerformanceLedgerError(msg)
        if raw_run.options_fingerprint != first.options_fingerprint:
            msg = "Measurement record mixes benchmark options."
            raise PerformanceLedgerError(msg)
    if first.environment != environment:
        msg = "Manifest environment does not match embedded raw benchmark context."
        raise PerformanceLedgerError(msg)
    expected_revision = (
        first.commit if not first.dirty else f"{first.commit}+dirty:{first.benchmark_tree_sha256}"
    )
    if revision != expected_revision:
        msg = (
            f"Manifest revision '{revision}' does not match raw benchmark revision "
            f"'{expected_revision}'."
        )
        raise PerformanceLedgerError(msg)


def _validate_reference(
    *,
    reference: LedgerReference | None,
    suite: SuitePolicy,
    environment: BenchmarkEnvironment,
) -> None:
    if reference is None:
        return
    if reference.suite_sha256 != suite.suite_sha256:
        msg = f"Reference record '{reference.record_id}' uses a different suite policy."
        raise PerformanceLedgerError(msg)
    if reference.environment != environment:
        msg = f"Reference record '{reference.record_id}' uses a different environment."
        raise PerformanceLedgerError(msg)
    stable_scenarios = {scenario for scenario, policy in suite.scenarios.items() if policy.stable}
    if set(reference.subject_ops) != stable_scenarios:
        msg = f"Reference record '{reference.record_id}' uses a different stable scenario set."
        raise PerformanceLedgerError(msg)


def _build_scenario_results(
    *,
    score_set: MeasurementSetRecord,
    suite: SuitePolicy,
    parent: LedgerReference | None,
    original: LedgerReference | None,
) -> dict[str, ScenarioResult]:
    results: dict[str, ScenarioResult] = {}
    for scenario, scenario_policy in suite.scenarios.items():
        if not scenario_policy.stable:
            continue
        cells = {
            library: score_set.summaries.get((scenario, library)) for library in suite.libraries
        }
        subject_summary = _require_summary(cells[suite.subject])
        competitor_summaries = {
            library: _require_summary(cells[library])
            for library, policy in scenario_policy.cells.items()
            if policy.status is CellStatus.COMPARABLE
        }
        fastest_competitor, fastest_summary = max(
            competitor_summaries.items(),
            key=lambda item: item[1].headline_ops_per_second,
        )
        ratio = subject_summary.headline_ops_per_second / fastest_summary.headline_ops_per_second
        results[scenario] = ScenarioResult(
            cells=cells,
            fastest_competitor=fastest_competitor,
            fastest_competitor_ops_per_second=fastest_summary.headline_ops_per_second,
            competitive_ratio=ratio,
            meets_margin=ratio >= MARGIN_TARGET,
            parent_diwire_ratio=_reference_ratio(
                scenario=scenario,
                candidate_ops=subject_summary.headline_ops_per_second,
                reference=parent,
            ),
            original_diwire_ratio=_reference_ratio(
                scenario=scenario,
                candidate_ops=subject_summary.headline_ops_per_second,
                reference=original,
            ),
        )
    return results


def _reference_ratio(
    *,
    scenario: str,
    candidate_ops: float,
    reference: LedgerReference | None,
) -> float:
    if reference is None:
        return 1.0
    return candidate_ops / reference.subject_ops[scenario]


def _quality_warnings(
    measurement_sets: Sequence[MeasurementSetRecord],
) -> tuple[str, ...]:
    warnings: list[str] = []
    for measurement in measurement_sets:
        for (scenario, library), summary in measurement.summaries.items():
            if summary.outlier_run_ids:
                warnings.append(
                    f"{measurement.manifest.measurement_id}:{library}/{scenario} has "
                    f"independent-run outliers: {', '.join(summary.outlier_run_ids)}"
                )
            if summary.sample_cv is not None and summary.sample_cv > _HIGH_CV_THRESHOLD:
                warnings.append(
                    f"{measurement.manifest.measurement_id}:{library}/{scenario} has "
                    f"sample CV {summary.sample_cv:.2%}"
                )
    return tuple(warnings)


def _find_outlier_run_ids(runs: Sequence[IndependentRun]) -> tuple[str, ...]:
    if len(runs) < _MIN_OUTLIER_RUNS:
        return ()
    values = [run.stats.mean_ops_per_second for run in runs]
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    median_deviation = statistics.median(deviations)
    if median_deviation == 0:
        return tuple(run.run_id for run, value in zip(runs, values, strict=True) if value != median)
    return tuple(
        run.run_id
        for run, value in zip(runs, values, strict=True)
        if abs(0.6745 * (value - median) / median_deviation) > _OUTLIER_MODIFIED_Z_THRESHOLD
    )


def _geometric_mean(values: Iterable[float]) -> float:
    value_list = list(values)
    if not value_list or any(value <= 0 or not math.isfinite(value) for value in value_list):
        msg = "Geometric mean requires finite positive values."
        raise PerformanceLedgerError(msg)
    return math.exp(math.fsum(math.log(value) for value in value_list) / len(value_list))


def _ledger_record_as_json(record: LedgerRecord) -> dict[str, object]:
    return {
        "schema_version": 1,
        "manifest": {
            "schema_version": record.manifest.schema_version,
            "record_id": record.manifest.record_id,
            "kind": record.manifest.kind,
            "revision": record.manifest.revision,
            "parent_record": (
                None
                if record.manifest.parent_record is None
                else str(record.manifest.parent_record)
            ),
            "original_record": (
                None
                if record.manifest.original_record is None
                else str(record.manifest.original_record)
            ),
            "environment": asdict(record.manifest.environment),
            "hypothesis": record.manifest.hypothesis,
            "conclusion": record.manifest.conclusion,
            "allocation_improvement_ratio": record.manifest.allocation_improvement_ratio,
        },
        "suite": {
            "schema_version": record.suite.schema_version,
            "suite_id": record.suite.suite_id,
            "suite_sha256": record.suite.suite_sha256,
            "subject": record.suite.subject,
            "libraries": list(record.suite.libraries),
        },
        "measurement_sets": [
            _measurement_set_as_json(measurement) for measurement in record.measurement_sets
        ],
        "scenarios": {
            scenario: _scenario_as_json(
                result=result,
                policy=record.suite.scenarios[scenario],
                libraries=record.suite.libraries,
            )
            for scenario, result in record.scenarios.items()
        },
        "score": asdict(record.score),
        "worst_parent_ratio": record.worst_parent_ratio,
        "quality_warnings": list(record.quality_warnings),
        "review_required": bool(record.quality_warnings),
    }


def _measurement_set_as_json(measurement: MeasurementSetRecord) -> dict[str, object]:
    return {
        "id": measurement.manifest.measurement_id,
        "role": measurement.manifest.role,
        "command": measurement.manifest.command,
        "raw_files": [str(path) for path in measurement.manifest.raw_files],
        "raw_metadata": [
            {
                "source_path": raw_run.source_path,
                "raw_sha256": raw_run.raw_sha256,
                "commit": raw_run.commit,
                "dirty": raw_run.dirty,
                "python_version": raw_run.python_version,
                "benchmark_tree_sha256": raw_run.benchmark_tree_sha256,
                "environment": asdict(raw_run.environment),
                "machine_fingerprint": raw_run.machine_fingerprint,
                "options_fingerprint": raw_run.options_fingerprint,
            }
            for raw_run in measurement.raw_runs
        ],
        "series": {
            f"{library}/{scenario}": _series_as_json(summary)
            for (scenario, library), summary in measurement.summaries.items()
        },
    }


def _scenario_as_json(
    *,
    result: ScenarioResult,
    policy: ScenarioPolicy,
    libraries: Sequence[str],
) -> dict[str, object]:
    return {
        "benchmark_file": policy.benchmark_file,
        "stable": policy.stable,
        "cells": {
            library: {
                "status": policy.cells[library].status.value,
                "reason": policy.cells[library].reason,
                "summary": _optional_series_as_json(result.cells[library]),
            }
            for library in libraries
        },
        "fastest_competitor": result.fastest_competitor,
        "fastest_competitor_ops_per_second": result.fastest_competitor_ops_per_second,
        "competitive_ratio": result.competitive_ratio,
        "meets_margin": result.meets_margin,
        "parent_diwire_ratio": result.parent_diwire_ratio,
        "original_diwire_ratio": result.original_diwire_ratio,
    }


def _series_as_json(summary: SeriesSummary) -> dict[str, object]:
    return {
        "headline_ops_per_second": summary.headline_ops_per_second,
        "arithmetic_mean_ops_per_second": summary.arithmetic_mean_ops_per_second,
        "sample_cv": summary.sample_cv,
        "outlier_run_ids": list(summary.outlier_run_ids),
        "runs": [
            {
                "run_id": run.run_id,
                "source_path": run.source_path,
                "datetime_utc": run.datetime_utc,
                "benchmark_name": run.benchmark_name,
                "benchmark_fullname": run.benchmark_fullname,
                "stats": asdict(run.stats),
            }
            for run in summary.runs
        ],
    }


def _optional_series_as_json(summary: SeriesSummary | None) -> dict[str, object] | None:
    if summary is None:
        return None
    return _series_as_json(summary)


def _require_summary(summary: SeriesSummary | None) -> SeriesSummary:
    if summary is None:
        msg = "Required benchmark summary is missing."
        raise PerformanceLedgerError(msg)
    return summary


def _extract_library(*, name: str, libraries: Sequence[str]) -> str:
    match = _BENCHMARK_NAME_PATTERN.match(name)
    if match is None:
        msg = f"Unexpected benchmark test name '{name}'."
        raise PerformanceLedgerError(msg)
    library = match.group("library")
    if library not in libraries:
        msg = f"Unexpected benchmark library '{library}'."
        raise PerformanceLedgerError(msg)
    return library


def _load_json_object(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return _cast_object(loaded, label=f"top-level JSON in '{path}'")


def _cast_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        msg = f"Expected {label} to be an object."
        raise PerformanceLedgerError(msg)
    return cast("dict[str, object]", value)


def _read_object(container: Mapping[str, object], *, key: str) -> dict[str, object]:
    return _cast_object(container.get(key), label=f"'{key}'")


def _read_list(container: Mapping[str, object], *, key: str) -> list[object]:
    value = container.get(key)
    if not isinstance(value, list):
        msg = f"Expected '{key}' to be a list."
        raise PerformanceLedgerError(msg)
    return cast("list[object]", value)


def _read_non_empty_str(container: Mapping[str, object], *, key: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value:
        msg = f"Expected '{key}' to be a non-empty string."
        raise PerformanceLedgerError(msg)
    return value


def _read_optional_str(container: Mapping[str, object], *, key: str) -> str | None:
    value = container.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        msg = f"Expected '{key}' to be a non-empty string or null."
        raise PerformanceLedgerError(msg)
    return value


def _read_unique_str_tuple(container: Mapping[str, object], *, key: str) -> tuple[str, ...]:
    values = _read_list(container, key=key)
    strings: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            msg = f"Expected every '{key}' entry to be a non-empty string."
            raise PerformanceLedgerError(msg)
        strings.append(value)
    if not strings or len(strings) != len(set(strings)):
        msg = f"Expected '{key}' to contain unique non-empty strings."
        raise PerformanceLedgerError(msg)
    return tuple(strings)


def _read_str_mapping(container: Mapping[str, object], *, key: str) -> dict[str, str]:
    payload = _read_object(container, key=key)
    mapping: dict[str, str] = {}
    for item_key, value in payload.items():
        if not isinstance(value, str) or not value:
            msg = f"Expected '{key}.{item_key}' to be a non-empty string."
            raise PerformanceLedgerError(msg)
        mapping[item_key] = value
    return mapping


def _read_bool(container: Mapping[str, object], *, key: str) -> bool:
    value = container.get(key)
    if not isinstance(value, bool):
        msg = f"Expected '{key}' to be a boolean."
        raise PerformanceLedgerError(msg)
    return value


def _read_int(container: Mapping[str, object], *, key: str) -> int:
    value = container.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"Expected '{key}' to be an integer."
        raise PerformanceLedgerError(msg)
    return value


def _read_positive_int(container: Mapping[str, object], *, key: str) -> int:
    value = _read_int(container, key=key)
    if value <= 0:
        msg = f"Expected '{key}' to be positive."
        raise PerformanceLedgerError(msg)
    return value


def _read_non_negative_int(container: Mapping[str, object], *, key: str) -> int:
    value = _read_int(container, key=key)
    if value < 0:
        msg = f"Expected '{key}' to be non-negative."
        raise PerformanceLedgerError(msg)
    return value


def _read_float(container: Mapping[str, object], *, key: str) -> float:
    value = container.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        msg = f"Expected '{key}' to be numeric."
        raise PerformanceLedgerError(msg)
    result = float(value)
    if not math.isfinite(result):
        msg = f"Expected '{key}' to be finite."
        raise PerformanceLedgerError(msg)
    return result


def _read_optional_float(container: Mapping[str, object], *, key: str) -> float | None:
    if container.get(key) is None:
        return None
    return _read_float(container, key=key)


def _read_positive_float(container: Mapping[str, object], *, key: str) -> float:
    value = _read_float(container, key=key)
    if value <= 0:
        msg = f"Expected '{key}' to be positive."
        raise PerformanceLedgerError(msg)
    return value


def _read_non_negative_float(container: Mapping[str, object], *, key: str) -> float:
    value = _read_float(container, key=key)
    if value < 0:
        msg = f"Expected '{key}' to be non-negative."
        raise PerformanceLedgerError(msg)
    return value


def _read_optional_path(
    container: Mapping[str, object],
    *,
    key: str,
    parent: Path,
) -> Path | None:
    value = container.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        msg = f"Expected '{key}' to be a non-empty path string or null."
        raise PerformanceLedgerError(msg)
    path = Path(value)
    return path if path.is_absolute() else parent / path


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
