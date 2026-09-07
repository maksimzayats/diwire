"""Measure one fresh-process import/startup operation without pre-importing DIWire.

Run directly with SCENARIO OUTPUT arguments. Only sys and the timer are imported
before measurement; metadata, validation and container teardown are outside it.
"""

from __future__ import annotations

import sys
from time import perf_counter_ns

SCENARIOS = ("import", "explicit", "autoregister", "settings_first", "diwire_first")


def measure_startup(scenario: str) -> dict[str, object]:
    if scenario not in SCENARIOS:
        raise ValueError("Unknown startup scenario")
    if any(
        name == package or name.startswith(f"{package}.")
        for name in sys.modules
        for package in ("diwire", "pydantic", "pydantic_settings", "pydantic_core")
    ):
        raise RuntimeError(
            "Subject and optional dependencies must not be imported before measurement"
        )

    started = perf_counter_ns()
    if scenario == "settings_first":
        import pydantic_settings
    dependency_imported = perf_counter_ns()

    from diwire import Container, DependencyRegistrationPolicy, Lifetime, MissingPolicy, Scope

    imported = perf_counter_ns()
    if scenario == "import":
        return {
            "total_ns": imported - started,
            "diwire_import_ns": imported - dependency_imported,
            "dependency_first_ns": dependency_imported - started,
            "post_import_ns": 0,
        }

    container = Container(
        missing_policy=MissingPolicy.ERROR
        if scenario == "explicit"
        else MissingPolicy.REGISTER_ROOT,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
        use_resolver_context=False,
    )
    if scenario in ("settings_first", "diwire_first"):
        import pydantic_settings

        class Settings(pydantic_settings.BaseSettings):
            model_config = pydantic_settings.SettingsConfigDict(env_prefix="DIWIRE_PERF_H007_")
            probe_value: int = 7

        first_settings = container.resolve(Settings)
        finished = perf_counter_ns()
        try:
            assert first_settings.probe_value == 7
            assert container.resolve(Settings) is first_settings
            registration = container._providers_registrations.get_by_type(Settings)
            assert registration.factory is not None
            assert registration.lifetime is Lifetime.SCOPED
            assert registration.scope is Scope.APP
        finally:
            container.close()
    else:

        class Service:
            pass

        if scenario == "explicit":
            container.add(Service, scope=Scope.APP, lifetime=Lifetime.TRANSIENT)
        first_service = container.resolve(Service)
        finished = perf_counter_ns()
        try:
            assert isinstance(first_service, Service)
        finally:
            container.close()
    return {
        "total_ns": finished - started,
        "diwire_import_ns": imported - dependency_imported,
        "dependency_first_ns": dependency_imported - started,
        "post_import_ns": finished - imported,
    }


def main() -> None:
    if len(sys.argv) != 3:
        raise ValueError("Expected SCENARIO OUTPUT arguments")
    scenario, output_path = sys.argv[1:]
    timings = measure_startup(scenario)
    loaded_optional_modules = sorted(
        name
        for name in sys.modules
        if any(
            name == package or name.startswith(f"{package}.")
            for package in ("pydantic", "pydantic_settings", "pydantic_core")
        )
    )

    # Metadata imports occur after the measured operation and optional-module snapshot.
    import gc
    import hashlib
    import importlib.metadata
    import json
    import os
    import platform
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]

    def version(package: str) -> str | None:
        try:
            return importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            return None

    distributions = {
        package: version(package) for package in ("pydantic", "pydantic-settings", "pydantic-core")
    }
    diwire_file = sys.modules["diwire"].__file__
    assert diwire_file is not None
    data = {
        "scenario": scenario,
        "timings_ns": timings,
        "loaded_optional_modules": loaded_optional_modules,
        "context": {
            "python_version": platform.python_version(),
            "python_executable": str(Path(sys.executable).resolve()),
            "python_prefix": sys.prefix,
            "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: True)(),
            "optimize": sys.flags.optimize,
            "trace_enabled": sys.gettrace() is not None,
            "profile_enabled": sys.getprofile() is not None,
            "instrumentation_environment": {
                key: os.environ.get(key) for key in ("PYTHONTRACEMALLOC", "PYTHONPROFILEIMPORTTIME")
            },
            "gc_enabled": gc.isenabled(),
            "platform": platform.platform(),
            "hash_seed": os.environ.get("PYTHONHASHSEED"),
            "power_state": os.environ.get("DIWIRE_BENCHMARK_POWER_STATE"),
            "dont_write_bytecode": sys.dont_write_bytecode,
            "pycache_prefix": sys.pycache_prefix,
            "distributions": distributions,
            "diwire_file": str(Path(diwire_file).resolve()),
            "source_sha256": {
                path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted((root / "src").rglob("*.py"))
            },
            "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "uv_lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
        },
    }
    with Path(output_path).open("x") as output:
        json.dump(data, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
