project = "diwire"
author = "Maksim Zayats"

extensions: list[str] = [
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

# Pyodide runner configuration
pyodide_runner_packages: list[str] = ["diwire"]
