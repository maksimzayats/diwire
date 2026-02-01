"""Sphinx extension that adds Run and Edit buttons to code blocks using Pyodide."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

__version__ = "0.1.0"

_STATIC_DIR = Path(__file__).parent / "_static"


class _SphinxConfig(Protocol):
    html_static_path: list[str]
    pyodide_runner_packages: list[str]
    pyodide_runner_selector: str
    pyodide_runner_pyodide_url: str


class _SphinxApp(Protocol):
    config: _SphinxConfig

    def add_config_value(self, name: str, default: Any, rebuild: str) -> None: ...

    def connect(self, event: str, callback: Any) -> None: ...

    def add_js_file(
        self,
        filename: str | None,
        *,
        body: str | None = None,
        priority: int | None = None,
    ) -> None: ...

    def add_css_file(self, filename: str) -> None: ...


def _builder_inited(app: _SphinxApp) -> None:
    app.config.html_static_path.append(str(_STATIC_DIR))

    packages = app.config.pyodide_runner_packages
    selector = app.config.pyodide_runner_selector
    pyodide_url = app.config.pyodide_runner_pyodide_url

    # Inject config as a global so the runner JS can read it.
    config_js = (
        "window.PYODIDE_RUNNER_CONFIG="
        + json.dumps({"packages": packages, "selector": selector})
        + ";"
    )
    app.add_js_file(None, body=config_js, priority=50)
    app.add_js_file(pyodide_url, priority=100)
    app.add_js_file("pyodide-runner-editor.js", priority=150)
    app.add_js_file("pyodide-runner.js", priority=200)
    app.add_css_file("pyodide-runner.css")


def setup(app: _SphinxApp) -> dict[str, Any]:
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
