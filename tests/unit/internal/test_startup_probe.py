from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.performance.startup_probe import SCENARIOS, measure_startup

_ROOT = Path(__file__).parents[3]


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("site_enabled", [True, False])
def test_startup_probe_measures_fresh_process_and_validates_resolution(
    tmp_path: Path,
    scenario: str,
    *,
    site_enabled: bool,
) -> None:
    settings = scenario in ("settings_first", "diwire_first")
    if settings and (not site_enabled or importlib.util.find_spec("pydantic_settings") is None):
        pytest.skip("Settings workload requires the optional dependency")
    output = tmp_path / "probe.json"
    command = [sys.executable, "-B"]
    if not site_enabled:
        command.append("-S")
    command.extend([str(_ROOT / "tests/performance/startup_probe.py"), scenario, str(output)])
    environment = {**os.environ, "PYTHONPATH": str(_ROOT / "src"), "PYTHONHASHSEED": "0"}
    # The executable, probe and arguments are explicit, and no shell is involved.
    subprocess.run(command, env=environment, check=True, capture_output=True, timeout=30)  # noqa: S603
    result = json.loads(output.read_text())
    timings = result["timings_ns"]
    assert timings["total_ns"] > 0
    assert timings["total_ns"] == (
        timings["dependency_first_ns"] + timings["diwire_import_ns"] + timings["post_import_ns"]
    )
    assert result["scenario"] == scenario
    assert result["context"]["dont_write_bytecode"] is True
    assert result["context"]["hash_seed"] == "0"
    assert result["context"]["diwire_file"] == str(_ROOT / "src/diwire/__init__.py")
    if not site_enabled:
        assert result["loaded_optional_modules"] == []
        assert all(version is None for version in result["context"]["distributions"].values())


def test_startup_probe_rejects_preimported_subject_and_unknown_scenarios() -> None:
    import diwire

    assert diwire.Container is not None
    with pytest.raises(RuntimeError, match="must not be imported"):
        measure_startup("import")
    with pytest.raises(ValueError, match="Unknown startup scenario"):
        measure_startup("unknown")


@pytest.mark.parametrize("package", ["pydantic", "pydantic_settings", "pydantic_core"])
def test_startup_probe_rejects_preloaded_optional_dependency(package: str) -> None:
    program = (
        "import sys, types\n"
        f"sys.modules[{package!r}] = types.ModuleType({package!r})\n"
        "from tests.performance.startup_probe import measure_startup\n"
        "measure_startup('import')\n"
    )
    # Fixed interpreter and test program, with no shell or imported subject.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", program],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "must not be imported before measurement" in result.stderr
