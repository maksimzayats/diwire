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
