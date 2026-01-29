# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
uv sync --group dev

# Development workflow
make format    # Format with ruff, auto-fix issues
make lint      # Run all checks: ruff, ty, pyrefly, mypy (strict)
make test      # Run tests with 100% coverage requirement

# Single test execution
uv run pytest tests/test_container.py::test_register
uv run pytest -k "keyword" tests/

# Benchmarks
make benchmark
```

## Architecture

diwire is a type-driven dependency injection container with zero runtime dependencies.

**Core modules** (`src/diwire/`):
- `container.py` - Main DI container: registration, resolution (sync/async), scoping, compilation
- `compiled_providers.py` - Optimized provider classes that eliminate runtime reflection
- `container_context.py` - Global context proxy for lazy container resolution via ContextVar
- `dependencies.py` - Type hint extraction with caching
- `exceptions.py` - 15+ custom exception types with detailed error messages
- `types.py` - `Lifetime` enum, `Injected` marker, `Factory` type alias

**Resolution flow**: Service request → check caches → get/auto-register → extract dependencies → resolve recursively → instantiate → cache by lifetime

**Key patterns**:
- Auto-registration enabled by default (container discovers dependencies from type hints)
- Compilation pre-processes the dependency graph into specialized providers for performance
- Scoped singletons use flat `(scope_key, service_key) -> instance` cache for O(1) lookups
- Async resolution parallelizes independent dependencies via `asyncio.gather()`

## Code Standards

- Python 3.10+ syntax: use `|` unions, `list[str]`, lowercase generics
- Line length: 100 characters
- Quotes: double quotes
- No relative imports in library code
- All public APIs must be fully typed (mypy strict mode)
- Raise exceptions from `src/diwire/exceptions.py` only
- 100% test coverage required (`fail_under = 100` in pyproject.toml)

## Testing

Tests in `tests/` use fixtures from `conftest.py`:
- `container()` - auto-registration enabled
- `container_no_autoregister()` - manual registration only
- `container_singleton()` - singleton as default lifetime

## Public API

Main exports from `diwire`:
- `Container` - DI container
- `Lifetime` - TRANSIENT, SINGLETON, SCOPED
- `Injected` - Mark function parameters for injection
- `Component` - Named component registration
- `container_context` - Global context for lazy resolution
