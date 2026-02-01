# sphinx-pyodide-runner

A Sphinx extension that adds **Run** and **Edit** buttons to code blocks, executing Python directly in the browser
via [Pyodide](https://pyodide.org/).

Designed to sit alongside [sphinx-copybutton](https://github.com/executablebooks/sphinx-copybutton) — all three
buttons (Edit, Run, Copy) appear on hover in the top-right corner of code blocks.

## Installation

```bash
uv add sphinx-pyodide-runner
```

## Usage

Add the extension to your Sphinx `conf.py`:

```python
extensions = [
    "sphinx_copybutton",
    "sphinx_pyodide_runner",
]
```

Then mark code blocks with the `py-run` class:

```rst
.. code-block:: python
   :class: py-run

   print("Hello from the browser!")
```

## Configuration

All values are optional and set in `conf.py`:

| Option                       | Default                                                      | Description                                       |
|------------------------------|--------------------------------------------------------------|---------------------------------------------------|
| `pyodide_runner_selector`    | `".py-run"`                                                  | CSS selector for code blocks to decorate          |
| `pyodide_runner_pyodide_url` | `"https://cdn.jsdelivr.net/pyodide/v0.29.3/full/pyodide.js"` | Pyodide CDN URL                                   |
| `pyodide_runner_packages`    | `[]`                                                         | Packages to install via micropip before execution |

Example:

```python
pyodide_runner_packages = ["numpy", "pandas"]
```

## Buttons

- **Edit** (pencil icon) — toggles `contenteditable` on the code block. Syntax highlighting is preserved during editing
  and restored on exit.
- **Run** (play icon) — loads Pyodide lazily, installs configured packages once, and executes the block. Output appears
  below.
- **Copy** (clipboard icon) — provided by sphinx-copybutton.
