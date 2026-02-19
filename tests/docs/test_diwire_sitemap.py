from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "diwire").is_dir():
            return candidate
    msg = f"Could not locate repository root from {start}"
    raise AssertionError(msg)


def _load_sitemap_module(repo_root: Path) -> ModuleType:
    module_path = repo_root / "docs" / "_extensions" / "diwire_sitemap.py"
    module_name = "diwire_sitemap_test_module"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        msg = f"Could not load module from {module_path}"
        raise AssertionError(msg)

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_html(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<html><body>ok</body></html>\n", encoding="utf-8")


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
SITEMAP: Any = _load_sitemap_module(REPO_ROOT)


def test_canonical_path_from_html_rel_maps_expected_shapes() -> None:
    assert SITEMAP._canonical_path_from_html_rel("index.html") == "/"
    assert SITEMAP._canonical_path_from_html_rel("core/index.html") == "/core/"
    assert SITEMAP._canonical_path_from_html_rel("core/async.html") == "/core/async/"


def test_write_extensionless_redirects_creates_redirect_for_non_index_pages(tmp_path: Path) -> None:
    source_html = tmp_path / "core" / "async.html"
    _write_html(source_html)

    SITEMAP._write_extensionless_redirects(
        tmp_path,
        html_files=[source_html],
        baseurl="https://docs.example.dev",
    )

    redirect_path = tmp_path / "core" / "async" / "index.html"
    assert redirect_path.is_file()

    redirect_html = redirect_path.read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://docs.example.dev/core/async/">' in redirect_html
    assert '<meta http-equiv="refresh" content="0; url=../async.html">' in redirect_html
    assert 'window.location.replace("../async.html");' in redirect_html


def test_write_extensionless_redirects_skips_index_pages(tmp_path: Path) -> None:
    root_index = tmp_path / "index.html"
    section_index = tmp_path / "core" / "index.html"
    _write_html(root_index)
    _write_html(section_index)

    SITEMAP._write_extensionless_redirects(
        tmp_path,
        html_files=[root_index, section_index],
        baseurl="https://docs.example.dev",
    )

    assert not (tmp_path / "index" / "index.html").exists()
    assert not (tmp_path / "core" / "index" / "index.html").exists()


def test_build_entries_uses_extensionless_canonical_urls(tmp_path: Path) -> None:
    _write_html(tmp_path / "index.html")
    _write_html(tmp_path / "core" / "index.html")
    _write_html(tmp_path / "core" / "async.html")

    entries = SITEMAP._build_entries(tmp_path, baseurl="https://docs.example.dev")
    locs = {entry.loc for entry in entries}

    assert locs == {
        "https://docs.example.dev/",
        "https://docs.example.dev/core/",
        "https://docs.example.dev/core/async/",
    }


def test_build_entries_ignores_generated_redirect_index_pages(tmp_path: Path) -> None:
    _write_html(tmp_path / "core" / "async.html")
    _write_html(tmp_path / "core" / "async" / "index.html")

    entries = SITEMAP._build_entries(tmp_path, baseurl="https://docs.example.dev")
    locs = [entry.loc for entry in entries]

    assert locs == ["https://docs.example.dev/core/async/"]
