from __future__ import annotations

import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import diwire
import diwire.exceptions as diwire_exceptions
import diwire.integrations.pytest_plugin as diwire_pytest_plugin

_EXPECTED_SNAPSHOT_PATH = Path(__file__).with_name("public_api_signatures_expected.txt")
_UPDATE_ENV_VAR = "DIWIRE_UPDATE_API_SIGNATURES"
_UPDATE_COMMAND = (
    "DIWIRE_UPDATE_API_SIGNATURES=1 uv run pytest tests/unit/public/test_public_api_signatures.py"
)
_ADDRESS_PATTERN = re.compile(r"0x[0-9a-fA-F]+")


def _normalize_snapshot_line(value: str) -> str:
    return _ADDRESS_PATTERN.sub("0x<ADDR>", value)


def _signature_marker(value: Any) -> str:
    try:
        signature = inspect.signature(value)
    except TypeError:
        return "<not-callable>"
    except ValueError:
        return "<no-signature>"
    return _normalize_snapshot_line(str(signature))


def _symbol_kind(value: object) -> str:
    if inspect.isclass(value):
        return "class"
    if callable(value):
        return "callable"
    return "object"


def _iter_public_diwire_methods(cls: type[Any]) -> list[tuple[str, Any]]:
    methods: list[tuple[str, Any]] = []
    for name, member in inspect.getmembers(cls):
        if name.startswith("_"):
            continue
        if not callable(member):
            continue

        module_name = getattr(member, "__module__", None)
        if not isinstance(module_name, str):
            continue
        if not module_name.startswith("diwire"):
            continue

        methods.append((name, member))
    return methods


def _collect_export_snapshot(module: ModuleType, export_names: list[str]) -> list[str]:
    lines: list[str] = []
    for export_name in export_names:
        exported_value = getattr(module, export_name)
        export_fq_name = f"{module.__name__}.{export_name}"
        lines.append(
            f"{export_fq_name} | {_symbol_kind(exported_value)} | "
            f"{_signature_marker(exported_value)}",
        )

        if not inspect.isclass(exported_value):
            continue

        for method_name, method in _iter_public_diwire_methods(exported_value):
            lines.append(f"{export_fq_name}.{method_name} | {_signature_marker(method)}")
    return lines


def _collect_module_exports_snapshot() -> list[str]:
    return _collect_export_snapshot(diwire, list(diwire.__all__))


def _collect_exceptions_snapshot() -> list[str]:
    exception_names = sorted(
        name
        for name, member in inspect.getmembers(diwire_exceptions, inspect.isclass)
        if not name.startswith("_") and member.__module__ == "diwire.exceptions"
    )
    return _collect_export_snapshot(diwire_exceptions, exception_names)


def _collect_pytest_plugin_snapshot() -> list[str]:
    return _collect_export_snapshot(diwire_pytest_plugin, list(diwire_pytest_plugin.__all__))


def _build_public_api_snapshot() -> str:
    snapshot_sections = [
        ("[diwire]", _collect_module_exports_snapshot()),
        ("[diwire.exceptions]", _collect_exceptions_snapshot()),
        ("[diwire.integrations.pytest_plugin]", _collect_pytest_plugin_snapshot()),
    ]

    lines: list[str] = []
    for section_header, section_lines in snapshot_sections:
        lines.append(section_header)
        lines.extend(_normalize_snapshot_line(line) for line in section_lines)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def test_public_api_signatures_match_expected_snapshot() -> None:
    current_snapshot = _build_public_api_snapshot()

    if os.getenv(_UPDATE_ENV_VAR) == "1":
        _EXPECTED_SNAPSHOT_PATH.write_text(current_snapshot, encoding="utf-8")
        return

    if not _EXPECTED_SNAPSHOT_PATH.exists():
        missing_snapshot_message = (
            f"Missing public API signatures snapshot.\nCreate it with:\n{_UPDATE_COMMAND}"
        )
        raise AssertionError(missing_snapshot_message)

    expected_snapshot = _EXPECTED_SNAPSHOT_PATH.read_text(encoding="utf-8")
    assert current_snapshot == expected_snapshot, (
        "Public API signatures snapshot mismatch.\n"
        f"If the change is intentional, update with:\n{_UPDATE_COMMAND}"
    )
