"""Run the bounded H005 experiment on one GitHub-hosted Linux subject checkout."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType
from typing import TextIO, cast

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
from tools.performance_ledger import compute_benchmark_tree_fingerprint

_SOURCE = "src/diwire/_internal/resolvers/assembly/compiler.py"
_POWER_LABEL = "GitHub-hosted Linux VM; host power policy unavailable"
_PAIR_COUNT = 5


def _read_json(path: Path) -> JsonObject:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        msg = f"Expected JSON object: {path}"
        raise TypeError(msg)
    return cast("JsonObject", value)


def _save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _command(command: list[str], *, cwd: Path, data: bytes | None = None) -> bytes:
    # Commands are constructed here from fixed executables and separate arguments; no shell.
    return subprocess.check_output(command, cwd=cwd, input=data, timeout=30)  # noqa: S603


def _interrupt(signum: int, _frame: FrameType | None) -> None:
    for controlled in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(controlled, signal.SIG_IGN)
    msg = f"Experiment interrupted by signal {signum}"
    raise KeyboardInterrupt(msg)


def _optional_read(path: str) -> str:
    candidate = Path(path)
    return candidate.read_text() if candidate.is_file() else "unavailable"


def _snapshot(cwd: Path) -> JsonObject:
    return {
        "time": time.time(),
        "power_state": _POWER_LABEL,
        "load_average": os.getloadavg(),
        "proc_stat": _optional_read("/proc/stat"),
        "cpu_stat": _optional_read("/sys/fs/cgroup/cpu.stat"),
        "cpu_quota": _optional_read("/sys/fs/cgroup/cpu.max"),
        "affinity": next(
            (
                line
                for line in Path("/proc/self/status").read_text().splitlines()
                if line.startswith("Cpus_allowed_list:")
            ),
            "unavailable",
        ),
        "processes": _command(["ps", "-Ao", "pid,pgid,pcpu,stat,comm"], cwd=cwd).decode(),
    }


class Experiment:
    """Own one frozen subject, its child processes and exact patch transitions."""

    def __init__(self, *, subject: Path, output: Path, protocol: Path, archive: Path) -> None:
        self.phase = "initialization"
        self.subject = subject.resolve()
        self.output = output.resolve()
        self.protocol = _read_json(protocol)
        self.source = self.subject / _SOURCE
        self.baseline = self.source.read_bytes()
        self.restoration_allowed = True
        self.deadline = time.monotonic() + self.protocol["maximum_job_seconds"]
        self.anchors: dict[str, JsonObject] = {}
        self.pair_values: dict[str, dict[str, list[tuple[float, float]]]] = {}
        self.cache = self.output / "empty-bytecode-cache"
        self.cache.mkdir()
        self.patch = self._load_patch(archive)
        self._check_subject()
        self.inputs = self._input_hashes()
        self.base_tree = compute_benchmark_tree_fingerprint(self.subject)

    def prepare(self, protocol: Path, archive: Path) -> None:
        """Inspect the candidate only after the controller owns restoration."""
        self.candidate = self._candidate_bytes()
        self._record_environment(protocol, archive)

    def _load_patch(self, archive: Path) -> bytes:
        raw = archive.read_bytes()
        if _digest(raw) != self.protocol["allocation_archive_sha256"]:
            raise ValueError("Allocation archive differs from frozen protocol")
        evidence = json.loads(gzip.decompress(raw))
        patch = evidence["candidate_patch"].encode()
        if _digest(patch) != self.protocol["patch_sha256"]:
            raise ValueError("Candidate patch differs from frozen protocol")
        (self.output / "candidate.patch").write_bytes(patch)
        stat = _command(["git", "apply", "--numstat", "-"], cwd=self.subject, data=patch).decode()
        if len(stat.splitlines()) != 1 or stat.splitlines()[0].split("\t")[-1] != _SOURCE:
            raise ValueError("Only the compiler patch is permitted")
        return cast("bytes", patch)

    def _check_subject(self) -> None:
        checkpoint = _command(["git", "rev-parse", "HEAD"], cwd=self.subject).decode().strip()
        if checkpoint != self.protocol["subject_commit"]:
            raise ValueError("Subject is not the frozen checkpoint")
        if _command(["git", "status", "--porcelain"], cwd=self.subject):
            raise ValueError("Subject must start clean")
        if _digest((self.subject / "uv.lock").read_bytes()) != self.protocol["lock_sha256"]:
            raise ValueError("Dependency lock changed")
        if (
            platform.system() != "Linux"
            or platform.python_version() != self.protocol["python_version"]
        ):
            raise ValueError("Require the declared Linux/Python environment")
        if not getattr(sys, "_is_gil_enabled", lambda: True)():
            raise ValueError("Protocol requires the GIL-enabled runtime")
        if self.protocol["pairs"] != _PAIR_COUNT:
            raise ValueError("Protocol requires exactly five initial pairs")

    def _input_hashes(self) -> dict[str, str]:
        paths = [
            *self.subject.joinpath("src").rglob("*.py"),
            *self.subject.joinpath("tests/benchmarks").rglob("*.py"),
            *self.subject.joinpath("tests/performance").rglob("*.py"),
            *(
                self.subject / name
                for name in (
                    "pyproject.toml",
                    "uv.lock",
                    "tools/performance_ledger.py",
                )
            ),
        ]
        paths.extend(
            path
            for name in (".python-version", "tests/conftest.py")
            if (path := self.subject / name).is_file()
        )
        return {
            path.relative_to(self.subject).as_posix(): _digest(path.read_bytes())
            for path in sorted(paths)
            if path != self.source
        }

    def _apply(self) -> None:
        _command(["git", "apply", "--check", "-"], cwd=self.subject, data=self.patch)
        _command(["git", "apply", "-"], cwd=self.subject, data=self.patch)

    def restore(self) -> None:
        """Reverse only the owned patch after all child processes have stopped."""
        if not self.restoration_allowed:
            raise RuntimeError("Live child cleanup unresolved; preserve subject for diagnosis")
        current = self.source.read_bytes()
        if current == self.baseline:
            return
        _command(["git", "apply", "--reverse", "--check", "-"], cwd=self.subject, data=self.patch)
        _command(["git", "apply", "--reverse", "-"], cwd=self.subject, data=self.patch)
        if self.source.read_bytes() != self.baseline:
            raise RuntimeError("Exact baseline restoration failed")

    def _candidate_bytes(self) -> bytes:
        try:
            self._apply()
            self.candidate = self.source.read_bytes()
            self.work_tree = compute_benchmark_tree_fingerprint(self.subject)
            return self.candidate
        finally:
            self.restore()

    def _record_environment(self, protocol: Path, archive: Path) -> None:
        controller = Path(__file__).parents[2]
        environment: JsonObject = {
            "protocol": self.protocol,
            "protocol_sha256": _digest(protocol.read_bytes()),
            "archive_sha256": _digest(archive.read_bytes()),
            "controller_commit": _command(["git", "rev-parse", "HEAD"], cwd=controller)
            .decode()
            .strip(),
            "controller_files": {
                path.name: _digest(path.read_bytes())
                for path in Path(__file__).parent.glob("remote_experiment*.py")
            },
            "python": sys.version,
            "python_executable": str(Path(sys.executable).resolve()),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "lscpu": _command(["lscpu", "--json"], cwd=self.subject).decode(),
            "uv": _command(["uv", "--version"], cwd=self.subject).decode().strip(),
            "dependencies": _command(
                ["uv", "pip", "freeze", "--python", str(self.subject / ".venv/bin/python")],
                cwd=self.subject,
            ).decode(),
            "runner": {
                name: os.environ.get(name, "unavailable")
                for name in (
                    "ImageOS",
                    "ImageVersion",
                    "RUNNER_NAME",
                    "RUNNER_ARCH",
                    "GITHUB_SHA",
                    "GITHUB_RUN_ID",
                    "GITHUB_RUN_ATTEMPT",
                )
            },
            "inputs": self.inputs,
            "initial_snapshot": _snapshot(self.subject),
        }
        if not environment["uv"].startswith(f"uv {self.protocol['uv_version']}"):
            raise ValueError("uv version differs from protocol")
        self.machine_anchor = {
            key: environment["initial_snapshot"][key]
            for key in ("power_state", "cpu_quota", "affinity")
        }
        _save(self.output / "environment.json", environment)

    def _live_group(self, group: int, child: subprocess.Popen[str]) -> bool:
        child.poll()
        rows = _command(["ps", "-Ao", "pgid=,stat="], cwd=self.subject).decode().splitlines()
        return any(
            int(fields[0]) == group and not fields[1].startswith("Z")
            for row in rows
            if len(fields := row.split()) >= 2
        )

    def _stop_child(self, child: subprocess.Popen[str]) -> None:
        self.restoration_allowed = False
        if not self._live_group(child.pid, child):
            child.wait(timeout=5)
            self.restoration_allowed = True
            return
        for control in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(child.pid, control)
            except (ProcessLookupError, PermissionError):
                if self._live_group(child.pid, child):
                    raise RuntimeError("Unable to stop owned process group") from None
            deadline = time.monotonic() + 5
            while self._live_group(child.pid, child) and time.monotonic() < deadline:
                time.sleep(0.05)
            if not self._live_group(child.pid, child):
                child.wait(timeout=5)
                self.restoration_allowed = True
                return
        raise RuntimeError("Owned child group remains alive")

    def _run_child(self, command: list[str], log: TextIO, entry: JsonObject) -> int:
        environment = dict(os.environ)
        environment.update(
            PYTHONHASHSEED="0",
            PYTHONPYCACHEPREFIX=str(self.cache),
            PYTHONDONTWRITEBYTECODE="1",
            DIWIRE_BENCHMARK_POWER_STATE=_POWER_LABEL,
        )
        pending: list[int] = []

        def defer(signum: int, _frame: FrameType | None) -> None:
            pending.append(signum)

        child: subprocess.Popen[str] | None = None
        handlers = {
            controlled: signal.getsignal(controlled)
            for controlled in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        }
        try:
            for controlled in handlers:
                signal.signal(controlled, defer)
            try:
                # Fixed executable and argument list; no shell. Handlers defer launch interrupts
                # without blocking signals inherited by the new process.
                child = subprocess.Popen(  # noqa: S603
                    command,
                    cwd=self.subject,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                self.restoration_allowed = False
                entry["child_group"] = child.pid
            finally:
                for controlled, handler in handlers.items():
                    signal.signal(controlled, handler)
            if pending:
                _interrupt(pending[0], None)
            remaining = max(1, self.deadline - time.monotonic())
            return child.wait(timeout=min(remaining, self.protocol["maximum_child_seconds"]))
        finally:
            try:
                if child is not None:
                    self._stop_child(child)
            finally:
                entry["child_cleanup_verified"] = self.restoration_allowed

    def _verify_snapshot(self, snapshot: JsonObject) -> None:
        if any(snapshot[key] != value for key, value in self.machine_anchor.items()):
            raise RuntimeError("Visible machine configuration changed")

    def _verify_source(self, expected: bytes) -> None:
        if self.source.read_bytes() != expected or self._input_hashes() != self.inputs:
            raise RuntimeError("Frozen subject inputs changed")
        if any(self.cache.rglob("*")):
            raise RuntimeError("Bytecode cache is not empty")

    def _read_run(
        self, path: Path, *, memory: bool, candidate: bool, nodes: list[str]
    ) -> dict[str, float]:
        raw = path.read_bytes()
        data = _read_json(path)
        context = invariant_payload(
            data,
            memory=memory,
            compiler_hash=_digest(self.candidate if candidate else self.baseline),
            tree_hash=self.work_tree if candidate else self.base_tree,
            inputs=self.inputs,
            checkpoint=self.protocol["subject_commit"],
            power_label=_POWER_LABEL,
            require_harness=any(name.startswith("tests/performance/") for name in nodes),
        )
        expected_gil = (
            context["gil_enabled"] is True if memory else context["gil_mode"] == "enabled"
        )
        if (
            context["python_version"] != self.protocol["python_version"]
            or context["python_executable"] != str((self.subject / ".venv/bin/python").resolve())
            or not expected_gil
            or context["uv_lock_sha256"] != self.protocol["lock_sha256"]
        ):
            raise ValueError("Child interpreter, GIL or lock differs from frozen protocol")
        kind = "memory" if memory else "timing"
        if kind in self.anchors and context != self.anchors[kind]:
            raise ValueError("Runtime, dependency or harness metadata changed across phases")
        self.anchors[kind] = context
        values = (
            validate_memory(data)
            if memory
            else validate_timing(
                data, {name: self.protocol["timing_cells"][name] for name in nodes}
            )
        )
        _save(path.with_suffix(".sha256.json"), {"sha256": _digest(raw)})
        return values

    def series(
        self,
        label: str,
        *,
        memory: bool,
        comparison: bool,
        nodes: list[str],
        start_pair: int = 1,
    ) -> dict[str, Effect]:
        """Run exactly five complete fresh-process pairs, preserving every artifact."""
        self.phase = label
        directory = self.output / label
        directory.mkdir(exist_ok=False)
        manifest: JsonObject = {
            "label": label,
            "memory": memory,
            "comparison": comparison,
            "start_pair": start_pair,
            "pairs": _PAIR_COUNT,
            "nodes": nodes,
            "runs": [],
        }
        values: dict[int, dict[str, dict[str, float]]] = {}
        try:
            for pair in range(start_pair, start_pair + _PAIR_COUNT):
                values[pair] = {}
                for role in ["base", "work"] if pair % 2 else ["work", "base"]:
                    values[pair][role] = self._series_run(
                        directory,
                        manifest,
                        pair=pair,
                        role=role,
                        memory=memory,
                        candidate=comparison and role == "work",
                        nodes=nodes,
                    )
        finally:
            try:
                self.restore()
            finally:
                _save(directory / "manifest.json", manifest)
        measurements = {
            key: [(values[pair]["base"][key], values[pair]["work"][key]) for pair in sorted(values)]
            for key in values[start_pair]["base"]
        }
        self.pair_values[label] = measurements
        result = {name: effect(pairs, memory=memory) for name, pairs in measurements.items()}
        _save(directory / "summary.json", {name: value.payload() for name, value in result.items()})
        return result

    def _series_run(
        self,
        directory: Path,
        manifest: JsonObject,
        *,
        pair: int,
        role: str,
        memory: bool,
        candidate: bool,
        nodes: list[str],
    ) -> dict[str, float]:
        self._verify_source(self.baseline)
        if time.monotonic() >= self.deadline:
            raise TimeoutError("Experiment time budget exhausted")
        if candidate:
            self._apply()
        expected = self.candidate if candidate else self.baseline
        self._verify_source(expected)
        name = f"{len(manifest['runs']) + 1:03}"
        output = directory / f"{name}.json"
        command = [str(self.subject / ".venv/bin/python"), "-m"]
        if memory:
            command += [
                "tests.performance.measure_compile_memory",
                "--output",
                str(output),
            ]
        else:
            command += ["pytest", *nodes, "--benchmark-only", f"--benchmark-json={output}", "-q"]
        entry: JsonObject = {
            "pair": pair,
            "role": role,
            "candidate": candidate,
            "artifact": output.name,
            "command": command,
            "before": _snapshot(self.subject),
            "compiler_sha256": _digest(expected),
        }
        self._verify_snapshot(entry["before"])
        manifest["runs"].append(entry)
        _save(directory / "manifest.json", manifest)
        try:
            with output.with_suffix(".log").open("x") as log:
                entry["returncode"] = self._run_child(command, log, entry)
        finally:
            try:
                entry["after"] = _snapshot(self.subject)
            finally:
                _save(directory / "manifest.json", manifest)
        self._verify_source(expected)
        self._verify_snapshot(entry["after"])
        if entry["returncode"]:
            msg = f"Benchmark child failed: {output}"
            raise RuntimeError(msg)
        result = self._read_run(output, memory=memory, candidate=candidate, nodes=nodes)
        entry["validated"] = True
        self.restore()
        _save(directory / "manifest.json", manifest)
        return result


def _confirm(experiment: Experiment, groups: dict[bool, set[str]]) -> str:
    tolerance = float(experiment.protocol["protection_percent"])
    band = float(experiment.protocol["confirmation_boundary_band"])
    unresolved_groups: dict[bool, set[str]] = {}
    rejected = False
    # Finish both initial groups before deciding whether the single extension wave is allowed.
    for memory, flags in groups.items():
        if not flags:
            continue
        kind = "memory" if memory else "timing"
        first = experiment.series(
            f"{kind}-confirmation",
            memory=memory,
            comparison=True,
            nodes=[] if memory else sorted(flags),
        )
        unresolved = {name for name in flags if ambiguous(first[name], tolerance, band)}
        rejected |= any(protection_flag(first[name], tolerance) for name in flags - unresolved)
        if unresolved:
            unresolved_groups[memory] = unresolved
    if rejected:
        return "rejected"
    combined: dict[str, Effect] = {}
    for memory, unresolved in unresolved_groups.items():
        kind = "memory" if memory else "timing"
        label = f"{kind}-confirmation"
        extension = f"{label}-extension"
        experiment.series(
            extension,
            memory=memory,
            comparison=True,
            nodes=[] if memory else sorted(unresolved),
            start_pair=6,
        )
        combined.update(
            {
                name: effect(
                    experiment.pair_values[label][name] + experiment.pair_values[extension][name],
                    memory=memory,
                )
                for name in unresolved
            }
        )
    _save(
        experiment.output / "confirmation-combined.json",
        {name: value.payload() for name, value in combined.items()},
    )
    if any(
        value.headline < -tolerance and value.paired < -tolerance for value in combined.values()
    ):
        return "rejected"
    return (
        "inconclusive"
        if any(protection_flag(value, tolerance) for value in combined.values())
        else "pass"
    )


def _evaluate(experiment: Experiment) -> str:
    tolerance = float(experiment.protocol["protection_percent"])
    calibration = experiment.series(
        "timing-aa", memory=False, comparison=False, nodes=experiment.protocol["calibration_cells"]
    )
    if any(outside_calibration(value, tolerance) for value in calibration.values()):
        return "deferred: timing calibration failed"
    allocation = experiment.series("memory-aa", memory=True, comparison=False, nodes=[])
    if any(outside_calibration(value, tolerance) for value in allocation.values()):
        return "deferred: memory calibration failed"
    memory = experiment.series("memory-ab", memory=True, comparison=True, nodes=[])
    target = float(experiment.protocol["memory_target_percent"])
    for size in (64, 256):
        value = memory[f"{size}:retained_bytes"]
        if value.headline < target or value.paired < target or value.wins != _PAIR_COUNT:
            return "rejected: memory target not reached"
    memory_flags = {name for name, value in memory.items() if protection_flag(value, tolerance)}
    timing = experiment.series(
        "timing-ab",
        memory=False,
        comparison=True,
        nodes=sorted(experiment.protocol["timing_cells"]),
    )
    timing_flags = {name for name, value in timing.items() if protection_flag(value, tolerance)}
    _save(
        experiment.output / "protection-flags.json",
        {"memory": sorted(memory_flags), "timing": sorted(timing_flags)},
    )
    verdict = _confirm(experiment, {True: memory_flags, False: timing_flags})
    if verdict != "pass":
        return f"{verdict}: protected workload confirmation"
    return "measurement gates passed; semantic and quality gates still required"


def main() -> int:
    """Execute the single preregistered job without automatic retries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    args = parser.parse_args()
    for controlled in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(controlled, _interrupt)
    args.output.mkdir(exist_ok=False, parents=True)
    experiment: Experiment | None = None
    report: JsonObject = {"decision": "incomplete", "phase": "initialization"}
    returncode = 1
    try:
        experiment = Experiment(
            subject=args.subject, output=args.output, protocol=args.protocol, archive=args.archive
        )
        experiment.prepare(args.protocol, args.archive)
        report["phase"] = "evaluation"
        report["decision"] = _evaluate(experiment)
        returncode = 0 if report["decision"].startswith("measurement gates passed") else 2
    except BaseException as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        try:
            if experiment is not None:
                experiment.restore()
        except BaseException as error:
            report["restoration_error"] = {"type": type(error).__name__, "message": str(error)}
            returncode = 1
        finally:
            report["phase"] = experiment.phase if experiment is not None else "initialization"
            report["finished"] = time.time()
            report["source_restored"] = (
                experiment.source.read_bytes() == experiment.baseline
                if experiment is not None and experiment.source.is_file()
                else None
            )
            report["child_cleanup_verified"] = (
                experiment.restoration_allowed if experiment is not None else None
            )
            _save(args.output / "decision.json", report)
    sys.stdout.write(json.dumps(report) + "\n")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
