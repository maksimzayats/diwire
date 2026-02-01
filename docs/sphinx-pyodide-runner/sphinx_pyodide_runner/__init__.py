"""Sphinx extension that adds Run and Edit buttons to code blocks using Pyodide."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sphinx.application import Sphinx

__version__ = "0.1.0"

_STATIC_DIR = Path(__file__).parent / "_static"


def _builder_inited(app: Sphinx) -> None:
    app.config.html_static_path.append(str(_STATIC_DIR))  # type: ignore[attr-defined]

    packages: list[str] = app.config.pyodide_runner_packages  # type: ignore[attr-defined]
    selector: str = app.config.pyodide_runner_selector  # type: ignore[attr-defined]
    pyodide_url: str = app.config.pyodide_runner_pyodide_url  # type: ignore[attr-defined]

    # Inject config as a global so the runner JS can read it.
    import json

    config_js = (
        "window.PYODIDE_RUNNER_CONFIG="
        + json.dumps({"packages": packages, "selector": selector})
        + ";"
    )
    app.add_js_file(None, body=config_js, priority=50)
    app.add_js_file(pyodide_url, priority=100)  # type: ignore[arg-type]
    app.add_js_file("pyodide-runner.js", priority=200)
    app.add_css_file("pyodide-runner.css")


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_config_value(
        "pyodide_runner_selector",
        default=".py-run",
        rebuild="html",
    )
    app.add_config_value(
        "pyodide_runner_pyodide_url",
        default="https://cdn.jsdelivr.net/pyodide/v0.29.3/full/pyodide.js",
        rebuild="html",
    )
    app.add_config_value(
        "pyodide_runner_packages",
        default=[],
        rebuild="html",
    )

    app.connect("builder-inited", _builder_inited)

    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
