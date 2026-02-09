.PHONY: format lint test docs benchmark

format:
	uv run ruff format .
	uv run ruff check --fix-only .

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .

test:
	uv run pytest tests/ --benchmark-skip --cov=src/diwire --cov-report=term-missing

test-all-pythons:
	uv run --python 3.10 pytest tests/ --benchmark-skip --cov=src/diwire --cov-report=term-missing
	uv run --python 3.14 pytest tests/ --benchmark-skip --cov=src/diwire --cov-report=term-missing
	uv run --python 3.14t pytest tests/ --benchmark-skip --cov=src/diwire --cov-report=term-missing

docs:
	rm -rf docs/_build
	uv run sphinx-build -b html docs docs/_build/html

# === Benchmark Commands ===

benchmark:
	uv run pytest tests/benchmarks/test_enter_close_scope_no_resolve.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_enter_close_scope_resolve_once.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_enter_close_scope_resolve_100.py --benchmark-only --benchmark-columns=ops -q
