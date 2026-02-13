from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import diwire


def _iter_class_defined_public_methods(
    cls: type[Any],
) -> list[tuple[str, Callable[..., Any]]]:
    methods: list[tuple[str, Callable[..., Any]]] = []
    for method_name, member in cls.__dict__.items():
        if method_name.startswith("_"):
            continue

        method_func: Callable[..., Any] | None = None
        if inspect.isfunction(member):
            method_func = member
        elif isinstance(member, staticmethod | classmethod):
            method_func = member.__func__

        if method_func is None:
            continue
        methods.append((method_name, method_func))

    return sorted(methods, key=lambda item: item[0])


def test_top_level_exported_api_objects_and_public_methods_have_docstrings() -> None:
    missing_object_docstrings: list[str] = []
    missing_method_docstrings: list[str] = []

    for export_name in sorted(diwire.__all__):
        exported_obj = getattr(diwire, export_name)

        if not inspect.getdoc(exported_obj):
            missing_object_docstrings.append(export_name)

        if not inspect.isclass(exported_obj):
            continue

        for method_name, method_func in _iter_class_defined_public_methods(exported_obj):
            if not inspect.getdoc(method_func):
                missing_method_docstrings.append(f"{exported_obj.__name__}.{method_name}")

    failure_lines: list[str] = []
    if missing_object_docstrings:
        failure_lines.append(
            "missing object docstrings: " + ", ".join(sorted(missing_object_docstrings)),
        )
    if missing_method_docstrings:
        failure_lines.append(
            "missing method docstrings: " + ", ".join(sorted(missing_method_docstrings)),
        )

    if failure_lines:
        raise AssertionError("\n".join(failure_lines))
