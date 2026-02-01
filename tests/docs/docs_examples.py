"""Utilities for testing example code embedded in the docs.

The docs are the single source of truth for runnable examples. We extract Python
code blocks marked with a dedicated CSS class and execute them in tests to
prevent drift between documentation and behavior.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RstCodeBlock:
    path: Path
    lineno: int
    classes: frozenset[str]
    code: str


_CODE_BLOCK_RE = re.compile(r"^(?P<indent>\s*)\.\. code-block::\s+(?P<lang>\w+)\s*$")


def iter_rst_code_blocks(*, docs_dir: Path) -> list[RstCodeBlock]:
    """Return all Python ``code-block`` directives from ``docs_dir``.

    The parser is intentionally minimal: it only understands the subset of RST
    we use for code blocks and directive options.
    """
    blocks: list[RstCodeBlock] = []
    for path in sorted(docs_dir.rglob("*.rst")):
        blocks.extend(_extract_from_file(path))
    return blocks


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _skip_blank_lines(lines: list[str], start: int) -> int:
    i = start
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    return i


def _parse_class_option(line: str) -> set[str]:
    stripped = line.strip()
    if not stripped.startswith(":class:"):
        return set()
    value = stripped[len(":class:") :].strip()
    return set(value.split()) if value else set()


def _parse_directive_options(
    *,
    lines: list[str],
    start: int,
    directive_indent: int,
) -> tuple[frozenset[str], int]:
    i = start
    classes: set[str] = set()

    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            return frozenset(classes), i + 1

        if _indent_of(line) <= directive_indent:
            return frozenset(classes), i

        classes |= _parse_class_option(line)
        i += 1

    return frozenset(classes), i


def _parse_directive_content(
    *,
    lines: list[str],
    start: int,
    directive_indent: int,
) -> tuple[list[str], int, int | None]:
    """Return (content_lines, next_index, content_indent_or_None)."""
    first_content = _skip_blank_lines(lines, start)
    if first_content >= len(lines):
        return [], first_content, None

    content_indent = _indent_of(lines[first_content])
    if content_indent <= directive_indent:
        return [], first_content + 1, None

    i = start
    content_lines: list[str] = []
    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            content_lines.append("")
            i += 1
            continue

        if _indent_of(line) <= directive_indent:
            break

        content_lines.append(line[content_indent:])
        i += 1

    return content_lines, i, content_indent


def _extract_from_file(path: Path) -> list[RstCodeBlock]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    blocks: list[RstCodeBlock] = []
    i = 0
    while i < len(lines):
        match = _CODE_BLOCK_RE.match(lines[i])
        if match is None:
            i += 1
            continue

        directive_indent = len(match.group("indent"))
        lang = match.group("lang")
        i += 1

        classes, i = _parse_directive_options(
            lines=lines,
            start=i,
            directive_indent=directive_indent,
        )

        # Capture directive content (indented block).
        content_start = i
        content_lines, i, content_indent = _parse_directive_content(
            lines=lines,
            start=i,
            directive_indent=directive_indent,
        )
        if content_indent is None:
            continue

        if lang == "python":
            code = textwrap.dedent("\n".join(content_lines)).rstrip() + "\n"
            blocks.append(
                RstCodeBlock(
                    path=path,
                    lineno=content_start + 1,
                    classes=frozenset(classes),
                    code=code,
                ),
            )

    return blocks
