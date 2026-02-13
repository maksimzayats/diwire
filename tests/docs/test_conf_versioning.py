from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "diwire").is_dir():
            return candidate
    msg = f"Could not locate repository root from {start}"
    raise AssertionError(msg)


def _load_docs_conf_module(repo_root: Path) -> ModuleType:
    conf_path = repo_root / "docs" / "conf.py"
    spec = importlib.util.spec_from_file_location("diwire_docs_conf", conf_path)
    if spec is None or spec.loader is None:
        msg = f"Could not load docs config module from {conf_path}"
        raise AssertionError(msg)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
DOCS_CONF = _load_docs_conf_module(REPO_ROOT)


def test_resolve_docs_versions_uses_non_placeholder_metadata_release() -> None:
    def fail_if_called(_: Path) -> str | None:
        msg = "git fallback must not be used for non-placeholder metadata versions"
        raise AssertionError(msg)

    release, version = DOCS_CONF._resolve_docs_versions(
        metadata_release="1.2.3",
        repo_root=REPO_ROOT,
        git_tag_reader=fail_if_called,
    )
    assert release == "1.2.3"
    assert version == "1.2.3"


def test_resolve_docs_versions_falls_back_to_latest_git_tag_for_placeholder_versions() -> None:
    release, version = DOCS_CONF._resolve_docs_versions(
        metadata_release="0.0.0.post7+gabcdef",
        repo_root=REPO_ROOT,
        git_tag_reader=lambda _: "v0.1.0",
    )
    assert release == "0.1.0"
    assert version == "0.1.0"


def test_resolve_docs_versions_hides_version_when_placeholder_and_no_tag() -> None:
    release, version = DOCS_CONF._resolve_docs_versions(
        metadata_release="0.0.0.post7",
        repo_root=REPO_ROOT,
        git_tag_reader=lambda _: None,
    )
    assert release == ""
    assert version == ""


@pytest.mark.parametrize(
    ("metadata_release", "expected_version"),
    [
        ("1.2.3.dev4", "1.2.3"),
        ("1.2.3.post7", "1.2.3"),
        ("1.2.3+gabcdef", "1.2.3"),
        ("1.2.3.post7.dev4+gabcdef", "1.2.3"),
    ],
)
def test_resolve_docs_versions_normalizes_display_version(
    metadata_release: str,
    expected_version: str,
) -> None:
    release, version = DOCS_CONF._resolve_docs_versions(
        metadata_release=metadata_release,
        repo_root=REPO_ROOT,
        git_tag_reader=lambda _: None,
    )
    assert release == metadata_release
    assert version == expected_version
