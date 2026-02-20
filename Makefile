.PHONY: format lint test docs examples-readme benchmark benchmark-json benchmark-report benchmark-report-all benchmark-json-resolve benchmark-report-resolve

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

examples-readme:
	uv run python -m tools.generate_examples_readme

# === Benchmark Commands ===

benchmark:
	uv run pytest tests/benchmarks/test_enter_close_scope_no_resolve.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_enter_close_scope_resolve_once.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_enter_close_scope_resolve_100_instance.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_enter_close_scope_resolve_scoped_100.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_resolve_deep_transient_chain.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_resolve_wide_transient_graph.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_resolve_singleton.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_resolve_transient.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_resolve_scoped.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_resolve_mixed_lifetimes.py --benchmark-only --benchmark-columns=ops -q
	uv run pytest tests/benchmarks/test_resolve_generated_scoped_grid.py --benchmark-only --benchmark-columns=ops -q

benchmark-json:
	mkdir -p benchmark-results
	uv run pytest tests/benchmarks --benchmark-only -q --benchmark-json=benchmark-results/raw-benchmark.json

benchmark-report: benchmark-json
	uv run python -m tools.benchmark_reporting \
		--input benchmark-results/raw-benchmark.json \
		--markdown benchmark-results/benchmark-table.md \
		--json benchmark-results/benchmark-table.json \
		--comment benchmark-results/pr-comment.md \
		--libraries diwire,rodi,dishka,wireup

benchmark-report-all: benchmark-json
	uv run python -m tools.benchmark_reporting \
		--input benchmark-results/raw-benchmark.json \
		--markdown benchmark-results/benchmark-table-all.md \
		--json benchmark-results/benchmark-table-all.json \
		--comment benchmark-results/pr-comment-all.md \
		--libraries diwire,rodi,dishka,wireup,punq

benchmark-json-resolve:
	mkdir -p benchmark-results
	uv run pytest \
		tests/benchmarks/test_resolve_transient.py \
		tests/benchmarks/test_resolve_singleton.py \
		tests/benchmarks/test_resolve_deep_transient_chain.py \
		tests/benchmarks/test_resolve_wide_transient_graph.py \
		tests/benchmarks/test_resolve_generated_scoped_grid.py \
		--benchmark-only -q --benchmark-json=benchmark-results/raw-benchmark-resolve.json

benchmark-report-resolve: benchmark-json-resolve
	uv run python -m tools.benchmark_reporting \
		--input benchmark-results/raw-benchmark-resolve.json \
		--markdown benchmark-results/benchmark-table-resolve.md \
		--json benchmark-results/benchmark-table-resolve.json \
		--comment benchmark-results/pr-comment-resolve.md \
		--libraries diwire,rodi,dishka,wireup
