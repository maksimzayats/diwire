.PHONY: format lint test docs benchmark

format:
	uv run ruff format .
	uv run ruff check --fix-only .

lint:
	uv run ruff check .
	uv run ty check src/
	uv run pyrefly check
	uv run mypy .

test:
	uv run pytest tests/ --benchmark-skip --cov=src/diwire --cov-report=term-missing

docs:
	rm -rf docs/_build
	uv run sphinx-build -b html docs docs/_build/html

# === Benchmark Commands ===

benchmark:
	uv run pytest tests/benchmarks/test_singleton_resolution.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_wide_singleton_resolution.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_transient_chain_resolution.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_request_scoped_resolution.py --benchmark-only --benchmark-columns=ops -q
