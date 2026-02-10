from __future__ import annotations

import importlib
import warnings
from typing import Any

_PYDANTIC_V1_WARNING_PATTERN = (
    r"Core Pydantic V1 functionality isn't compatible with Python 3\.14 or greater\."
)


def _load_pydantic_settings_base() -> type[Any] | None:
    return _load_base_settings("pydantic_settings")


def _load_pydantic_v1_base() -> type[Any] | None:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=_PYDANTIC_V1_WARNING_PATTERN,
            category=UserWarning,
        )
        pydantic_v1_base = _load_base_settings("pydantic.v1")
        if pydantic_v1_base is not None:
            return pydantic_v1_base
        return _load_base_settings("pydantic")


def _load_base_settings(module_name: str) -> type[Any] | None:
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
    base_settings = getattr(module, "BaseSettings", None)
    if isinstance(base_settings, type):
        return base_settings
    return None


def _build_settings_bases() -> tuple[type[Any], ...]:
    seen_ids: set[int] = set()
    bases: list[type[Any]] = []

    for candidate in (_load_pydantic_settings_base(), _load_pydantic_v1_base()):
        if candidate is None:
            continue
        candidate_id = id(candidate)
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)
        bases.append(candidate)

    return tuple(bases)


SETTINGS_BASES: tuple[type[Any], ...] = _build_settings_bases()


def is_pydantic_settings_subclass(candidate: object) -> bool:
    """Return true when candidate subclasses a supported Pydantic settings base."""
    if not isinstance(candidate, type):
        return False
    return any(issubclass(candidate, base) for base in SETTINGS_BASES)


__all__ = [
    "SETTINGS_BASES",
    "is_pydantic_settings_subclass",
]
