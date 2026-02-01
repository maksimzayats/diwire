"""Tiny, dependency-free sitemap generator for SEO.

This intentionally stays minimal (and vendored) to avoid pulling extra docs
dependencies into the library.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from sphinx.errors import ExtensionError


class _SphinxConfig(Protocol):
    html_baseurl: str


class _SphinxBuilder(Protocol):
    format: str


class _SphinxApp(Protocol):
    builder: _SphinxBuilder
    config: _SphinxConfig
    outdir: str

    def add_config_value(self, name: str, default: Any, rebuild: str) -> None: ...

    def connect(self, event: str, callback: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class _SitemapEntry:
    loc: str
    lastmod: str


def _iter_html_files(outdir: Path) -> list[Path]:
    # Sphinx outputs a lot of internal files; we only want real pages.
    html_files: list[Path] = []
    for path in outdir.rglob("*.html"):
        rel = path.relative_to(outdir).as_posix()
        if rel.startswith(("_static/", "_sources/", "_modules/")):
            continue
        if rel in {"genindex.html", "search.html"}:
            continue
        html_files.append(path)

    # Stable ordering helps keep diffs small (and makes local debugging nicer).
    html_files.sort(key=lambda p: p.relative_to(outdir).as_posix())
    return html_files


def _build_entries(outdir: Path, *, baseurl: str) -> list[_SitemapEntry]:
    base = baseurl.rstrip("/") + "/"
    entries: list[_SitemapEntry] = []
    for html_path in _iter_html_files(outdir):
        rel = html_path.relative_to(outdir).as_posix()
        loc = base + rel
        lastmod = (
            datetime.fromtimestamp(html_path.stat().st_mtime, tz=timezone.utc).date().isoformat()
        )
        entries.append(_SitemapEntry(loc=loc, lastmod=lastmod))
    return entries


def _write_sitemap(outdir: Path, entries: list[_SitemapEntry]) -> None:
    # Keep XML output stable and small; don't add unnecessary optional tags.
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for entry in entries:
        lines.extend(
            [
                "  <url>",
                f"    <loc>{entry.loc}</loc>",
                f"    <lastmod>{entry.lastmod}</lastmod>",
                "  </url>",
            ],
        )
    lines.append("</urlset>")

    (outdir / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_robots(outdir: Path, *, baseurl: str) -> None:
    base = baseurl.rstrip("/") + "/"
    content = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "",
            f"Sitemap: {base}sitemap.xml",
            "",
        ],
    )
    (outdir / "robots.txt").write_text(content, encoding="utf-8")


def _build_finished(app: _SphinxApp, exc: Exception | None) -> None:
    if exc is not None:
        return
    if app.builder.format != "html":
        return

    baseurl = app.config.html_baseurl.strip()
    if not baseurl:
        return

    outdir = Path(app.outdir)
    entries = _build_entries(outdir, baseurl=baseurl)
    if not entries:
        return

    _write_sitemap(outdir, entries)
    _write_robots(outdir, baseurl=baseurl)


def setup(app: _SphinxApp) -> dict[str, Any]:
    # We use the built-in `html_baseurl` config as the canonical site URL.
    # Some Sphinx versions predefine it; treat that as OK.
    with contextlib.suppress(ExtensionError):
        app.add_config_value("html_baseurl", default="", rebuild="html")
    app.connect("build-finished", _build_finished)

    return {
        "version": "0.1.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
