from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

BEGIN_MARKER = "<!-- BEGIN: AUTO-GENERATED EXAMPLES -->"
END_MARKER = "<!-- END: AUTO-GENERATED EXAMPLES -->"
_DESCRIPTION = "Generate examples/README.md from examples/ex_* files."

_TOPIC_PATTERN = re.compile(r"^ex_(?P<index>\d+)_((?P<slug>[a-z0-9_]+))$")
_NUMERIC_PREFIX_PATTERN = re.compile(r"^(?P<index>\d+)_")
_SMALL_WORDS = frozenset({"a", "an", "and", "as", "at", "for", "in", "of", "on", "or", "the", "to"})
_TOKEN_MAP = {
    "api": "API",
    "fastapi": "FastAPI",
    "msgspec": "msgspec",
    "pydantic": "Pydantic",
    "pytest": "Pytest",
    "uuid": "UUID",
}


@dataclass(frozen=True, slots=True)
class ExampleFile:
    """Represents one example module rendered into the generated README."""

    path: Path
    relative_path: Path
    anchor: str
    docstring_markdown: str | None
    code: str


@dataclass(frozen=True, slots=True)
class Topic:
    """Represents one topic folder and its example modules."""

    index: int
    slug: str
    path: Path
    anchor: str
    title: str
    files: tuple[ExampleFile, ...]


def discover_topics(examples_root: Path) -> list[Topic]:
    topic_entries: list[tuple[int, str, Path]] = []
    for candidate in examples_root.iterdir():
        if not candidate.is_dir():
            continue
        match = _TOPIC_PATTERN.fullmatch(candidate.name)
        if match is None:
            continue
        index = int(match.group("index"))
        slug = match.group("slug")
        topic_entries.append((index, slug, candidate))

    topic_entries.sort(key=lambda item: (item[0], item[1]))
    topics: list[Topic] = []
    for index, slug, topic_path in topic_entries:
        topic_anchor = _topic_anchor(index=index, slug=slug)
        files = _discover_topic_files(
            examples_root=examples_root,
            topic_path=topic_path,
            topic_anchor=topic_anchor,
        )
        topics.append(
            Topic(
                index=index,
                slug=slug,
                path=topic_path,
                anchor=topic_anchor,
                title=title_from_slug(slug),
                files=tuple(files),
            ),
        )
    return topics


def title_from_slug(slug: str) -> str:
    tokens = slug.split("_")
    titled_tokens: list[str] = []
    for index, token in enumerate(tokens):
        mapped = _TOKEN_MAP.get(token)
        if mapped is None:
            mapped = token.capitalize()
        if index > 0 and token in _SMALL_WORDS:
            mapped = token
        titled_tokens.append(mapped)
    return " ".join(titled_tokens)


def split_module_docstring(source: str) -> tuple[str | None, str]:
    module = ast.parse(source)
    code_without_docstring = source
    if module.body and _is_docstring_expr(module.body[0]):
        docstring_node = module.body[0]
        end_lineno = docstring_node.end_lineno
        if end_lineno is None:
            msg = "Module docstring node is missing end line information."
            raise ValueError(msg)
        start_lineno = docstring_node.lineno
        source_lines = source.splitlines(keepends=True)
        remaining_lines = source_lines[: start_lineno - 1] + source_lines[end_lineno:]
        code_without_docstring = "".join(remaining_lines)

    cleaned_docstring = ast.get_docstring(module, clean=True)
    code_without_docstring = code_without_docstring.lstrip("\n")
    return cleaned_docstring, code_without_docstring


def render_generated_markdown(topics: list[Topic]) -> str:
    buffer = StringIO()
    buffer.write("### Table of Contents\n\n")
    for topic in topics:
        buffer.write(f"- [{topic.index:02d}. {topic.title}](#{topic.anchor})\n")
    buffer.write("\n")

    for topic in topics:
        buffer.write(f'<a id="{topic.anchor}"></a>\n')
        buffer.write(f"## {topic.index:02d}. {topic.title}\n\n")
        buffer.write("Files:\n")
        for example_file in topic.files:
            file_display_name = _topic_file_display_name(topic, example_file)
            buffer.write(f"- [{file_display_name}](#{example_file.anchor})\n")
        buffer.write("\n")

        for example_file in topic.files:
            relative_path_text = example_file.relative_path.as_posix()
            file_name = _topic_file_display_name(topic, example_file)
            buffer.write(f'<a id="{example_file.anchor}"></a>\n')
            buffer.write(
                f"### {file_name} ([{relative_path_text}]({relative_path_text}))\n\n",
            )
            if example_file.docstring_markdown:
                buffer.write(f"{example_file.docstring_markdown}\n\n")
            buffer.write("```python\n")
            buffer.write(example_file.code)
            if not example_file.code.endswith("\n"):
                buffer.write("\n")
            buffer.write("```\n\n")

    return buffer.getvalue().rstrip("\n") + "\n"


def replace_marked_region(readme_text: str, new_region: str) -> str:
    lines = readme_text.splitlines(keepends=True)
    begin_indices = [idx for idx, line in enumerate(lines) if line.strip() == BEGIN_MARKER]
    end_indices = [idx for idx, line in enumerate(lines) if line.strip() == END_MARKER]
    if len(begin_indices) != 1:
        msg = f"Expected exactly one begin marker line: {BEGIN_MARKER}"
        raise ValueError(msg)
    if len(end_indices) != 1:
        msg = f"Expected exactly one end marker line: {END_MARKER}"
        raise ValueError(msg)

    begin_index = begin_indices[0]
    end_index = end_indices[0]
    if end_index <= begin_index:
        msg = "End marker must appear after begin marker."
        raise ValueError(msg)

    prefix = "".join(lines[: begin_index + 1])
    suffix = "".join(lines[end_index:])
    trimmed_region = new_region.strip("\n")
    replacement = f"\n{trimmed_region}\n" if trimmed_region else "\n"
    return f"{prefix}{replacement}{suffix}"


def build_updated_readme_text(*, readme_text: str, examples_root: Path) -> str:
    topics = discover_topics(examples_root)
    generated_region = render_generated_markdown(topics)
    return replace_marked_region(readme_text, generated_region)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when examples/README.md is not up-to-date.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    examples_root = repo_root / "examples"
    readme_path = examples_root / "README.md"
    current_text = readme_path.read_text(encoding="utf-8")
    updated_text = build_updated_readme_text(readme_text=current_text, examples_root=examples_root)

    if args.check:
        if current_text != updated_text:
            msg = "examples/README.md is out of sync. Run: uv run python -m tools.generate_examples_readme\n"
            sys.stderr.write(msg)
            return 1
        return 0

    if current_text != updated_text:
        readme_path.write_text(updated_text, encoding="utf-8")
    return 0


def _discover_topic_files(
    *,
    examples_root: Path,
    topic_path: Path,
    topic_anchor: str,
) -> list[ExampleFile]:
    topic_files: list[Path] = []
    for candidate in topic_path.rglob("*.py"):
        if "__pycache__" in candidate.parts:
            continue
        topic_files.append(candidate)

    topic_files.sort(key=lambda path: _topic_file_sort_key(path.relative_to(topic_path)))

    discovered: list[ExampleFile] = []
    for path in topic_files:
        relative_path = path.relative_to(examples_root)
        source = path.read_text(encoding="utf-8")
        docstring_markdown, code = split_module_docstring(source)
        file_anchor = f"{topic_anchor}--{_slugify(relative_path.name)}"
        discovered.append(
            ExampleFile(
                path=path,
                relative_path=relative_path,
                anchor=file_anchor,
                docstring_markdown=docstring_markdown,
                code=code,
            ),
        )
    return discovered


def _is_docstring_expr(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _topic_anchor(*, index: int, slug: str) -> str:
    return f"ex-{index:02d}-{slug.replace('_', '-')}"


def _topic_file_display_name(topic: Topic, example_file: ExampleFile) -> str:
    relative_to_topic = example_file.relative_path.relative_to(topic.path.name)
    if relative_to_topic.parent == Path():
        return relative_to_topic.name
    return relative_to_topic.as_posix()


def _topic_file_sort_key(path: Path) -> tuple[int, int, str]:
    match = _NUMERIC_PREFIX_PATTERN.match(path.name)
    if match is not None:
        return (0, int(match.group("index")), path.as_posix())
    return (1, 0, path.as_posix())


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return re.sub(r"-{2,}", "-", normalized).strip("-")


if __name__ == "__main__":
    raise SystemExit(main())
