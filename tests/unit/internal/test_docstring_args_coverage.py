from __future__ import annotations

import ast
import re
from pathlib import Path

SECTION_HEADING_RE = re.compile(r"^[A-Z][A-Za-z ]*:$")
ARG_ENTRY_RE = re.compile(r"^([*]{0,2}[A-Za-z_][A-Za-z0-9_]*)\s*:")


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "diwire").is_dir():
            return candidate
    msg = f"Could not locate repository root from {start}"
    raise AssertionError(msg)


def _iter_target_files() -> list[Path]:
    repo_root = _find_repo_root(Path(__file__).resolve())
    src_root = repo_root / "src" / "diwire"
    return sorted(src_root.rglob("*.py"))


def _iter_non_private_docstring_callables(
    tree: ast.AST,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    callables: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        if not ast.get_docstring(node):
            continue
        callables.append(node)
    return sorted(callables, key=lambda item: (item.lineno, item.col_offset, item.name))


def _parameter_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    names = [arg.arg for arg in node.args.args]
    if names and names[0] in {"self", "cls"}:
        names = names[1:]
    names.extend(arg.arg for arg in node.args.kwonlyargs)
    if node.args.vararg is not None:
        names.append(node.args.vararg.arg)
    if node.args.kwarg is not None:
        names.append(node.args.kwarg.arg)
    return names


def _documented_arg_names(docstring: str) -> set[str]:
    lines = docstring.splitlines()
    start_index = None
    for index, line in enumerate(lines):
        if line.strip() == "Args:":
            start_index = index + 1
            break

    if start_index is None:
        return set()

    names: set[str] = set()
    for line in lines[start_index:]:
        stripped = line.strip()
        if not stripped:
            continue
        if SECTION_HEADING_RE.match(stripped):
            break
        match = ARG_ENTRY_RE.match(stripped)
        if match is None:
            continue
        names.add(match.group(1).lstrip("*"))
    return names


def test_non_private_docstrings_document_all_parameters_in_args_section() -> None:
    missing_entries: list[str] = []
    for path in _iter_target_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for callable_node in _iter_non_private_docstring_callables(tree):
            parameter_names = _parameter_names(callable_node)
            if not parameter_names:
                continue

            docstring = ast.get_docstring(callable_node)
            if docstring is None:
                continue

            documented_names = _documented_arg_names(docstring)
            if not documented_names:
                missing_entries.append(
                    f"{path}:{callable_node.lineno}:{callable_node.name}: missing Args section",
                )
                continue

            missing_parameters = [name for name in parameter_names if name not in documented_names]
            if missing_parameters:
                missing_entries.append(
                    f"{path}:{callable_node.lineno}:{callable_node.name}: missing "
                    f"{', '.join(missing_parameters)}",
                )

    if missing_entries:
        msg = "Missing docstring parameter descriptions:\n" + "\n".join(sorted(missing_entries))
        raise AssertionError(msg)
