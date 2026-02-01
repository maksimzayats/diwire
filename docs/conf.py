from __future__ import annotations

import os
import sys
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

# Ensure the local package is importable for autodoc without requiring an install step.
_DOCS_DIR = Path(__file__).resolve().parent
_ROOT = _DOCS_DIR.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_DOCS_DIR / "_extensions"))

project = "diwire"
author = "Maksim Zayats"

try:
    release = package_version("diwire")
except PackageNotFoundError:
    release = "0+unknown"

# Used by Sphinx + templates. Keep `version` stable-ish (major.minor.patch) even when `release` includes dev/local info.
version = (
    release.split("+", maxsplit=1)[0].split(".post", maxsplit=1)[0].split(".dev", maxsplit=1)[0]
)

extensions: list[str] = [
    # Built-in Sphinx extensions
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.autosectionlabel",
    "sphinx_copybutton",
    "sphinx_pyodide_runner",
]

root_doc = "index"
source_suffix: dict[str, str] = {
    ".rst": "restructuredtext",
}

exclude_patterns: list[str] = ["_build"]

html_theme = "furo"
html_static_path: list[str] = ["_static"]
html_css_files: list[str] = ["custom.css"]
templates_path: list[str] = ["_templates"]
html_theme_options = {
    "source_repository": "https://github.com/maksimzayats/diwire",
    "source_branch": os.environ.get("DIWIRE_DOCS_SOURCE_BRANCH", "main"),
    "source_directory": "docs",
    "top_of_page_buttons": ["view", "edit"],
}

# ---- Quality of life / navigation -------------------------------------------------

autosectionlabel_prefix_document = True
autosummary_generate = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# ---- SEO-ish defaults -------------------------------------------------------------

html_title = "diwire: type-driven dependency injection for Python"

# If you set a base URL, we'll emit a sitemap and robots.txt (see docs/_extensions/diwire_sitemap.py).
# Default to the canonical docs domain, but allow contributors to disable by setting DIWIRE_DOCS_BASEURL="".
html_baseurl = os.environ.get("DIWIRE_DOCS_BASEURL", "https://docs.diwire.dev").strip()
if html_baseurl:
    extensions.append("diwire_sitemap")

html_meta = {
    "description": (
        "diwire is a dependency injection container for Python 3.10+ that builds object graphs "
        "from type hints alone. Supports scoped lifetimes, async resolution, generator-based "
        "cleanup, open generics, and zero runtime dependencies."
    ),
    "keywords": (
        "dependency injection, python dependency injection, di container, inversion of control, "
        "type hints, typed dependency injection, fastapi dependency injection"
    ),
}

# Pyodide runner configuration
pyodide_runner_packages: list[str] = ["diwire"]
