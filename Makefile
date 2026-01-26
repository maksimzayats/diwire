format:
	uv run ruff format .
	uv run ruff check --fix-only .

lint:
	uv run ruff check .
	uv run ty check src/
	uv run pyrefly check
	uv run mypy .

test:
	uv run pytest tests/ --cov=src/diwire --cov-report=term-missing

# === Benchmark Commands ===

benchmark:
	@echo "=== Simple Resolution ==="
	@uv run pytest benchmarks/test_simple_resolution.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Singleton Cache ==="
	@uv run pytest benchmarks/test_singleton_cache.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Transient Resolution ==="
	@uv run pytest benchmarks/test_transient_resolution.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Deep Chain ==="
	@uv run pytest benchmarks/test_deep_chain.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Wide Graph ==="
	@uv run pytest benchmarks/test_wide_graph.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Scoped Resolution ==="
	@uv run pytest benchmarks/test_scoped_resolution.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Container Setup ==="
	@uv run pytest benchmarks/test_container_setup.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Cold Resolution ==="
	@uv run pytest benchmarks/test_cold_resolution.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Async Simple Resolution ==="
	@uv run pytest benchmarks/test_async_simple_resolution.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Async Factory ==="
	@uv run pytest benchmarks/test_async_factory.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Async Deep Chain ==="
	@uv run pytest benchmarks/test_async_deep_chain.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Async Wide Graph ==="
	@uv run pytest benchmarks/test_async_wide_graph.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Async Scoped Resolution ==="
	@uv run pytest benchmarks/test_async_scoped_resolution.py --benchmark-only --benchmark-columns=ops -q
	@echo "\n=== Async Generator ==="
	@uv run pytest benchmarks/test_async_generator.py --benchmark-only --benchmark-columns=ops -q
