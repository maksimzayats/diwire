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

import pytest


@dataclass(frozen=True, slots=True)
class CodeBlock:
    doc_path: Path
    header_line: int
    code: str


_CODE_BLOCK_DIRECTIVE_RE = re.compile(r"^(?P<indent>[ \t]*)\.\.\s+code-block::\s+python\s*$")
_RESOLVER_CONTEXT_USE_RE = re.compile(r"(^\s*@resolver_context\b|resolver_context\.)", re.MULTILINE)
_RESOLVER_CONTEXT_IMPORT_RE = re.compile(
    r"^\s*from\s+diwire\s+import\s+.*\bresolver_context\b",
    re.MULTILINE,
)

_OPTIONAL_DOC_DEPS: frozenset[str] = frozenset({"django", "fastapi", "flask", "starlette"})


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "diwire").is_dir():
            return candidate
    msg = f"Could not locate repository root from {start}"
    raise AssertionError(msg)


def _discover_rst_files(docs_root: Path) -> list[Path]:
    rst_files: list[Path] = []
    for path in docs_root.rglob("*.rst"):
        if "_build" in path.parts:
            continue
        rst_files.append(path)
    return sorted(rst_files)


def _indent_len(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _skip_blank_lines(lines: list[str], start: int) -> int:
    i = start
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    return i


def _skip_code_block_options(lines: list[str], start: int, base_indent_len: int) -> int:
    i = start
    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            return i
        if _indent_len(line) <= base_indent_len:
            return i
        if line.lstrip(" \t").startswith(":"):
            i += 1
            continue
        return i
    return i


def _consume_indented_block(
    lines: list[str], start: int, content_indent_len: int
) -> tuple[str, int]:
    i = start
    code_lines: list[str] = []
    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            code_lines.append("")
            i += 1
            continue
        if _indent_len(line) < content_indent_len:
            break
        code_lines.append(line[content_indent_len:])
        i += 1

    return "\n".join(code_lines).rstrip(), i


def _extract_python_code_blocks(doc_path: Path) -> list[CodeBlock]:
    text = doc_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    blocks: list[CodeBlock] = []

    i = 0
    while i < len(lines):
        match = _CODE_BLOCK_DIRECTIVE_RE.match(lines[i])
        if match is None:
            i += 1
            continue

        base_indent_len = len(match.group("indent"))
        header_line = i + 1

        i += 1
        i = _skip_code_block_options(lines, i, base_indent_len=base_indent_len)
        i = _skip_blank_lines(lines, i)

        if i >= len(lines):
            break

        first_content_line = lines[i]
        first_indent_len = _indent_len(first_content_line)
        if first_indent_len <= base_indent_len:
            continue

        code, i = _consume_indented_block(lines, i, content_indent_len=first_indent_len)
        blocks.append(
            CodeBlock(
                doc_path=doc_path,
                header_line=header_line,
                code=code,
            )
        )

    return blocks


def _parse_code_block_or_raise(*, block: CodeBlock, repo_root: Path) -> None:
    try:
        rel_path = block.doc_path.relative_to(repo_root)
        ast.parse(block.code, filename=f"{rel_path}:{block.header_line}")
    except SyntaxError as exc:  # pragma: no cover
        rel_path = block.doc_path.relative_to(repo_root)
        msg = (
            f"Invalid python syntax in docs code block: {rel_path}:{block.header_line}\n"
            f"{type(exc).__name__}: {exc}"
        )
        raise AssertionError(msg) from exc


def _assert_code_blocks_parse(blocks: list[CodeBlock], repo_root: Path) -> None:
    for block in blocks:
        _parse_code_block_or_raise(block=block, repo_root=repo_root)


def _assert_resolver_context_imports(blocks: list[CodeBlock], repo_root: Path) -> None:
    all_code = "\n\n".join(block.code for block in blocks)
    if not _RESOLVER_CONTEXT_USE_RE.search(all_code):
        return

    if _RESOLVER_CONTEXT_IMPORT_RE.search(all_code):
        return

    rel_path = blocks[0].doc_path.relative_to(repo_root) if blocks else "<unknown>"
    msg = (
        f"{rel_path} uses resolver_context but does not import it. "
        "Add `from diwire import resolver_context` (or include it in an existing import)."
    )
    raise AssertionError(msg)


def _module_name_for_doc(doc_path: Path) -> str:
    digest = hashlib.sha256(str(doc_path).encode("utf-8")).hexdigest()[:12]
    return f"diwire_docs_code_blocks_{digest}"


def _build_script(blocks: list[CodeBlock], repo_root: Path) -> tuple[str, list[tuple[int, str]]]:
    script_lines: list[str] = []
    markers: list[tuple[int, str]] = []

    for block in blocks:
        rel_path = block.doc_path.relative_to(repo_root)
        marker = f"# --- {rel_path}:{block.header_line} ---"
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
    return f"Docs snippet execution failed: {rel_path}\n{type(exc).__name__}: {exc}{marker_note}"


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
DOCS_ROOT = REPO_ROOT / "docs"
RST_FILES = _discover_rst_files(DOCS_ROOT)


@pytest.mark.parametrize("doc_path", RST_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_docs_python_code_blocks_execute(doc_path: Path) -> None:
    blocks = _extract_python_code_blocks(doc_path)

    _assert_code_blocks_parse(blocks, repo_root=REPO_ROOT)
    _assert_resolver_context_imports(blocks, repo_root=REPO_ROOT)

    if not blocks:
        return

    script, markers = _build_script(blocks, repo_root=REPO_ROOT)
    module_name = _module_name_for_doc(doc_path)
    module = _module_for_exec(module_name=module_name, doc_path=doc_path)

    sys.modules[module_name] = module
    try:
        compiled = compile(script, filename=str(doc_path), mode="exec")
        exec(compiled, module.__dict__)  # noqa: S102
    except ModuleNotFoundError as exc:
        missing = (exc.name or "").split(".", 1)[0]
        if missing in _OPTIONAL_DOC_DEPS:
            pytest.skip(
                f"{doc_path.relative_to(REPO_ROOT)} requires optional dependency: {missing}"
            )
        msg = _execution_failure_message(
            doc_path=doc_path,
            repo_root=REPO_ROOT,
            markers=markers,
            exc=exc,
        )
        raise AssertionError(msg) from exc
    except Exception as exc:
        msg = _execution_failure_message(
            doc_path=doc_path,
            repo_root=REPO_ROOT,
            markers=markers,
            exc=exc,
        )
        raise AssertionError(msg) from exc
    finally:
        sys.modules.pop(module_name, None)
