# Agent Notes for diwire

This repository is a Python 3.10+ library. Use strict linting, typing, and
testing standards. Prefer uv for all tooling and keep changes compatible with
the current public API.

## Quick commands

- Install deps (dev): `uv sync --dev`
- Format: `make format`
- Lint (all): `make lint`
- Test (all): `make test`

## Build

- Build wheel/sdist: `uv build`
- Clean build artifacts manually if needed (no scripted clean target)

## Lint and type checks

- Always keep linting and type-checking clean; do not proceed with changes that introduce errors.
- Ruff lint: `uv run ruff check .`
- Ruff auto-fix (limited): `uv run ruff check --fix-only .`
- Ruff format: `uv run ruff format .`
- ty type checks: `uv run ty check .`
- pyrefly checks: `uv run pyrefly check .`
- mypy (strict): `uv run mypy .`

## Tests

- Run all tests: `uv run pytest tests/`
- Run a single test file: `uv run pytest tests/test_container.py`
- Run a single test: `uv run pytest tests/test_container.py::test_register`
- Run tests with keyword filter: `uv run pytest -k "dependency" tests/`
- Coverage (recommended for new work):
  `uv run pytest --cov=diwire --cov-report=term-missing tests/`

## Repo structure

- Library source: `src/diwire/`
- Tests: `tests/`
- Examples (not API docs): `examples/`

## Style and formatting

- Line length: 100 (Ruff).
- Quotes: double quotes (Ruff format).
- Indent: 4 spaces.
- Format with Ruff before linting.
- Use ASCII unless the file already contains non-ASCII characters.

## Imports

- No relative imports in library code (Ruff tidy-imports bans them).
- Prefer explicit imports from `diwire` modules.
- Combine `as` imports when appropriate (`combine-as-imports = true`).
- Avoid unused imports; `__init__.py` is allowed to re-export.

## Typing and types

- Python minimum version is 3.10 (use `|` unions, `list[str]`, etc.).
- All new public APIs must be fully typed.
- mypy is strict; keep types precise and avoid `Any`.
- If `Any` is unavoidable, document why and keep scope minimal.
- Use `typing.Protocol` or `collections.abc` for public contracts.
- Prefer `Final` for constants that should not change.

## Naming conventions

- Classes: `PascalCase`.
- Functions and variables: `snake_case`.
- Constants: `UPPER_SNAKE_CASE`.
- Public API names should be stable and descriptive.
- Test names should describe the behavior and expectation.

## Error handling

- Raise library-specific exceptions from `src/diwire/exceptions.py`.
- Prefer explicit error messages over implicit failures.
- Avoid catching `Exception` unless re-raising with context.
- When adding new errors, update tests and docs/examples as needed.

## Docstrings and docs

- Ruff enforces many docstring rules, but D100/D103/etc. are ignored.
- Public APIs should still include clear docstrings.
- Example code in `examples/` can be lighter-weight and may include prints.

## Testing guidelines

- Aim for maximum coverage and edge cases for all new features.
- Maintain 100% coverage overall; every change must keep coverage at 100%.
- Tests live in `tests/` and mirror module naming when possible.
- Use pytest fixtures from `tests/conftest.py` for shared setup.
- Prefer small, focused tests over large integration tests.
- Keep tests deterministic; avoid time-based assertions unless necessary.

## Quality gates

- Always ensure linting and type-checking run clean with no errors.
- Every new change must preserve 100% test coverage.
- After making changes, always run `make lint` and `make test` and report results.

## Ruff configuration highlights

- `select = ["ALL"]` with targeted ignores.
- Tests allow `assert`, unused args, and some pytest patterns.
- `examples/` allows prints, commented code, and relaxed security rules.
- `container.py` has intentional complexity exemptions.

## Agent behavior

- Do not add new lint ignores without justification.
- Keep public API backward compatible unless explicitly requested.
- Preserve existing formatting and file organization.
- Avoid adding new dependencies unless required for functionality.
- Update or add tests whenever behavior changes.

## Notes about additional rules

- No Cursor rules found (.cursor/rules/ or .cursorrules).
- No GitHub Copilot instructions found (.github/copilot-instructions.md).
