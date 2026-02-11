from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

import diwire.integrations.pydantic_settings as pydantic_settings_integration


def test_load_base_settings_returns_none_for_missing_module(monkeypatch: Any) -> None:
    def _raise_import_error(_module_name: str) -> ModuleType:
        raise ImportError

    monkeypatch.setattr(importlib, "import_module", _raise_import_error)

    assert pydantic_settings_integration._load_base_settings("missing.module") is None


def test_load_base_settings_returns_none_when_base_settings_is_not_a_type(
    monkeypatch: Any,
) -> None:
    module = ModuleType("test_module")
    module.BaseSettings = "not-a-type"  # type: ignore[attr-defined]

    def _import_module(_module_name: str) -> ModuleType:
        return module

    monkeypatch.setattr(importlib, "import_module", _import_module)

    assert pydantic_settings_integration._load_base_settings("fake.module") is None


def test_load_pydantic_v1_base_falls_back_to_pydantic_module(monkeypatch: Any) -> None:
    class _FallbackBaseSettings:
        pass

    seen_module_names: list[str] = []

    def _load_base_settings(module_name: str) -> type[Any] | None:
        seen_module_names.append(module_name)
        if module_name == "pydantic.v1":
            return None
        if module_name == "pydantic":
            return _FallbackBaseSettings
        return None

    monkeypatch.setattr(
        pydantic_settings_integration,
        "_load_base_settings",
        _load_base_settings,
    )

    loaded = pydantic_settings_integration._load_pydantic_v1_base()
    assert loaded is _FallbackBaseSettings
    assert seen_module_names == ["pydantic.v1", "pydantic"]


def test_is_pydantic_settings_subclass_returns_false_for_non_type() -> None:
    assert pydantic_settings_integration.is_pydantic_settings_subclass("not-a-class") is False


def test_is_pydantic_settings_subclass_returns_false_on_issubclass_type_error(
    monkeypatch: Any,
) -> None:
    class _Candidate:
        pass

    monkeypatch.setattr(
        pydantic_settings_integration,
        "SETTINGS_BASES",
        ("not-a-class",),
    )

    assert pydantic_settings_integration.is_pydantic_settings_subclass(_Candidate) is False
