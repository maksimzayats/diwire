from __future__ import annotations

import importlib
import warnings
from typing import Any

from diwire._internal.type_checks import is_runtime_class

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
    """Return whether a class is a supported Pydantic settings model.

    DIWire checks both ``pydantic_settings.BaseSettings`` and legacy
    ``pydantic.v1.BaseSettings``/``pydantic.BaseSettings`` when available.
    If Pydantic is not installed, this function returns ``False`` for every
    candidate.

    DIWire uses this integration for safe autoregistration: settings subclasses
    are registered through a zero-argument factory and cached at the root scope.

    Args:
        candidate: Object to test.

    Returns:
        ``True`` when ``candidate`` is a runtime class and subclasses any
        discovered settings base; otherwise ``False``.

    """
    if not is_runtime_class(candidate):
        return False
    try:
        return any(issubclass(candidate, base) for base in SETTINGS_BASES)
    except TypeError:
        return False


__all__ = [
    "SETTINGS_BASES",
    "is_pydantic_settings_subclass",
]
