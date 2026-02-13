from __future__ import annotations

import ast
import hashlib
import importlib.machinery
import importlib.util
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True, slots=True)
class CodeBlock:
    doc_path: Path
    header_line: int
    code: str


_FENCE_BEGIN_RE = re.compile(r"^```python\s*$")
_FENCE_END_RE = re.compile(r"^```\s*$")


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "diwire").is_dir():
            return candidate
    msg = f"Could not locate repository root from {start}"
    raise AssertionError(msg)


def _extract_python_code_blocks(doc_path: Path) -> list[CodeBlock]:
    text = doc_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    blocks: list[CodeBlock] = []
    i = 0
    while i < len(lines):
        if _FENCE_BEGIN_RE.match(lines[i]) is None:
            i += 1
            continue

        header_line = i + 1
        i += 1
        code_lines: list[str] = []
        while i < len(lines) and _FENCE_END_RE.match(lines[i]) is None:
            code_lines.append(lines[i])
            i += 1

        code = "\n".join(code_lines).rstrip()
        blocks.append(CodeBlock(doc_path=doc_path, header_line=header_line, code=code))

        while i < len(lines) and _FENCE_END_RE.match(lines[i]) is None:
            i += 1
        if i < len(lines):
            i += 1

    return blocks


def _build_script(blocks: list[CodeBlock], repo_root: Path) -> tuple[str, list[tuple[int, str]]]:
    script_lines: list[str] = []
    markers: list[tuple[int, str]] = []
    rel_path = blocks[0].doc_path.relative_to(repo_root) if blocks else "<unknown>"

    for index, block in enumerate(blocks, start=1):
        marker = f"# --- {rel_path}:block:{index} ---"
        markers.append((len(script_lines) + 1, marker))
        script_lines.append(marker)
        if block.code:
            script_lines.extend(block.code.splitlines())
        script_lines.append("")

    return "\n".join(script_lines), markers


def _closest_marker(markers: list[tuple[int, str]], failing_line: int) -> str | None:
    best: str | None = None
    for marker_line, marker_text in markers:
        if marker_line <= failing_line:
            best = marker_text
        else:
            break
    return best


def _execution_failure_message(
    *, doc_path: Path, repo_root: Path, markers: list[tuple[int, str]], exc: BaseException
) -> str:
    extracted = traceback.extract_tb(exc.__traceback__)
    failing_line: int | None = None
    for frame in reversed(extracted):
        if frame.filename == str(doc_path):
            failing_line = frame.lineno
            break

    marker = _closest_marker(markers, failing_line) if failing_line is not None else None
    marker_note = f"\n{marker}" if marker else ""
    rel_path = doc_path.relative_to(repo_root)
    return f"README snippet execution failed: {rel_path}\n{type(exc).__name__}: {exc}{marker_note}"


def _module_name_for_doc(doc_path: Path) -> str:
    digest = hashlib.sha256(str(doc_path).encode("utf-8")).hexdigest()[:12]
    return f"diwire_repo_readme_code_blocks_{digest}"


def _module_for_exec(*, module_name: str, doc_path: Path) -> ModuleType:
    module = ModuleType(module_name)
    module.__file__ = str(doc_path)

    loader = importlib.machinery.SourceFileLoader(module_name, str(doc_path))
    spec = importlib.util.spec_from_loader(module_name, loader)
    if spec is None:
        msg = f"Could not create module spec for {doc_path}"
        raise AssertionError(msg)

    module.__loader__ = loader
    module.__spec__ = spec
    return module


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
README_PATH = REPO_ROOT / "README.md"


def test_repo_readme_python_code_blocks_execute() -> None:
    blocks = _extract_python_code_blocks(README_PATH)
    if not blocks:
        return

    script, markers = _build_script(blocks, repo_root=REPO_ROOT)
    ast.parse(script, filename=str(README_PATH))

    module_name = _module_name_for_doc(README_PATH)
    module = _module_for_exec(module_name=module_name, doc_path=README_PATH)

    sys.modules[module_name] = module
    try:
        compiled = compile(script, filename=str(README_PATH), mode="exec")
        exec(compiled, module.__dict__)  # noqa: S102
    except Exception as exc:
        msg = _execution_failure_message(
            doc_path=README_PATH,
            repo_root=REPO_ROOT,
            markers=markers,
            exc=exc,
        )
        raise AssertionError(msg) from exc
    finally:
        sys.modules.pop(module_name, None)
