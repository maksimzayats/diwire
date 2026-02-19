"""Tiny, dependency-free sitemap generator for SEO.

This intentionally stays minimal (and vendored) to avoid pulling extra docs
dependencies into the library.
"""

from __future__ import annotations

import contextlib
import html
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


def _canonical_path_from_html_rel(rel: str) -> str:
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return f"/{rel.removesuffix('index.html')}"
    return f"/{rel.removesuffix('.html')}/"


def _is_generated_redirect_index(rel: str, *, outdir: Path) -> bool:
    if not rel.endswith("/index.html"):
        return False

    non_index_rel = f"{rel.removesuffix('/index.html')}.html"
    return (outdir / non_index_rel).is_file()


def _iter_html_files(outdir: Path) -> list[Path]:
    # Sphinx outputs a lot of internal files; we only want real pages.
    html_files: list[Path] = []
    for path in outdir.rglob("*.html"):
        rel = path.relative_to(outdir).as_posix()
        if rel.startswith(("_static/", "_sources/", "_modules/")):
            continue
        if rel in {"genindex.html", "search.html"}:
            continue
        if _is_generated_redirect_index(rel, outdir=outdir):
            continue
        html_files.append(path)

    # Stable ordering helps keep diffs small (and makes local debugging nicer).
    html_files.sort(key=lambda p: p.relative_to(outdir).as_posix())
    return html_files


def _build_entries(outdir: Path, *, baseurl: str) -> list[_SitemapEntry]:
    base = baseurl.rstrip("/")
    entries: list[_SitemapEntry] = []
    for html_path in _iter_html_files(outdir):
        rel = html_path.relative_to(outdir).as_posix()
        loc = f"{base}{_canonical_path_from_html_rel(rel)}"
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


def _render_redirect_page(*, target_href: str, canonical_url: str) -> str:
    escaped_target = html.escape(target_href, quote=True)
    escaped_canonical = html.escape(canonical_url, quote=True)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "  <head>",
            '    <meta charset="utf-8">',
            "    <title>Redirecting...</title>",
            f'    <link rel="canonical" href="{escaped_canonical}">',
            f'    <meta http-equiv="refresh" content="0; url={escaped_target}">',
            f'    <script>window.location.replace("{escaped_target}");</script>',
            "  </head>",
            "  <body>",
            f'    <p>Redirecting to <a href="{escaped_target}">{escaped_target}</a>.</p>',
            "  </body>",
            "</html>",
            "",
        ],
    )


def _write_extensionless_redirects(outdir: Path, *, html_files: list[Path], baseurl: str) -> None:
    base = baseurl.rstrip("/")
    for html_path in html_files:
        rel = html_path.relative_to(outdir).as_posix()
        if rel.endswith("index.html"):
            continue

        source_name = Path(rel).name
        redirect_rel = Path(rel).with_suffix("") / "index.html"
        redirect_path = outdir / redirect_rel
        redirect_path.parent.mkdir(parents=True, exist_ok=True)

        canonical_url = f"{base}{_canonical_path_from_html_rel(rel)}"
        redirect_html = _render_redirect_page(
            target_href=f"../{source_name}",
            canonical_url=canonical_url,
        )
        redirect_path.write_text(redirect_html, encoding="utf-8")


def _build_finished(app: _SphinxApp, exc: Exception | None) -> None:
    if exc is not None:
        return
    if app.builder.format != "html":
        return

    baseurl = app.config.html_baseurl.strip()
    if not baseurl:
        return

    outdir = Path(app.outdir)
    html_files = _iter_html_files(outdir)
    if not html_files:
        return

    _write_extensionless_redirects(outdir, html_files=html_files, baseurl=baseurl)
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
