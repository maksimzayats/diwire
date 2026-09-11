# Local developer commands only. CI keeps critical commands inline.

[private]
default:
    @just --list

format:
    uv run ruff format .
    uv run ruff check --fix-only .

lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy .

test:
    uv run pytest tests/ --benchmark-skip --cov=src/diwire --cov-report=term-missing

[private]
_test-e2e framework:
    #!/bin/sh
    compose_file="tests/e2e/{{ framework }}/docker-compose.yml"
    docker compose -f "$compose_file" up --build --abort-on-container-exit --exit-code-from tests
    exit_code=$?
    docker compose -f "$compose_file" down --volumes --remove-orphans
    exit "$exit_code"

test-e2e-fastapi: (_test-e2e "fastapi")

test-e2e-aiohttp: (_test-e2e "aiohttp")

test-e2e-litestar: (_test-e2e "litestar")

test-e2e-flask: (_test-e2e "flask")

test-e2e-celery: (_test-e2e "celery")

test-e2e-typer: (_test-e2e "typer")

test-all-pythons:
    uv run --python 3.10 pytest tests/ --benchmark-skip --cov=src/diwire --cov-report=term-missing
    uv run --python 3.14 pytest tests/ --benchmark-skip --cov=src/diwire --cov-report=term-missing
    uv run --python 3.14t pytest tests/ --benchmark-skip --cov=src/diwire --cov-report=term-missing

docs:
    rm -rf docs/_build
    uv run sphinx-build -b html docs docs/_build/html

examples-readme:
    uv run python -m tools.generate_examples_readme

[private]
benchmark-artifact-dir:
    #!/bin/sh
    set -eu
    if [ -z "${BENCHMARK_ARTIFACT_DIR:-}" ]; then
        echo "BENCHMARK_ARTIFACT_DIR must name a unique directory for this run." >&2
        exit 2
    fi
    if [ -e "$BENCHMARK_ARTIFACT_DIR" ]; then
        echo "BENCHMARK_ARTIFACT_DIR already exists; choose a new directory." >&2
        exit 2
    fi
    mkdir -p "$(dirname "$BENCHMARK_ARTIFACT_DIR")"
    mkdir "$BENCHMARK_ARTIFACT_DIR"

benchmark: benchmark-diwire

benchmark-diwire: benchmark-artifact-dir
    uv run pytest tests/benchmarks -k "benchmark_diwire" --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/diwire.json" -q

benchmark-comparison: benchmark-artifact-dir
    uv run pytest tests/benchmarks/test_enter_close_scope_no_resolve.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/enter-close-scope-no-resolve.json" -q
    uv run pytest tests/benchmarks/test_enter_close_scope_resolve_once.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/enter-close-scope-resolve-once.json" -q
    uv run pytest tests/benchmarks/test_enter_close_scope_resolve_100_instance.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/enter-close-scope-resolve-100-instance.json" -q
    uv run pytest tests/benchmarks/test_enter_close_scope_resolve_scoped_100.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/enter-close-scope-resolve-scoped-100.json" -q
    uv run pytest tests/benchmarks/test_enter_close_scope_resolve_generator_request_try_finally.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/enter-close-scope-resolve-generator-request.json" -q
    uv run pytest tests/benchmarks/test_enter_close_scope_resolve_open_generic_scoped.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/enter-close-scope-resolve-open-generic-scoped.json" -q
    uv run pytest tests/benchmarks/test_resolve_deep_transient_chain.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/resolve-deep-transient-chain.json" -q
    uv run pytest tests/benchmarks/test_resolve_wide_transient_graph.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/resolve-wide-transient-graph.json" -q
    uv run pytest tests/benchmarks/test_resolve_singleton.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/resolve-singleton.json" -q
    uv run pytest tests/benchmarks/test_resolve_transient.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/resolve-transient.json" -q
    uv run pytest tests/benchmarks/test_resolve_open_generic_transient.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/resolve-open-generic-transient.json" -q
    uv run pytest tests/benchmarks/test_resolve_scoped.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/resolve-scoped.json" -q
    uv run pytest tests/benchmarks/test_resolve_scoped_with_registered_open_closed_generics.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/resolve-scoped-open-closed-generics.json" -q
    uv run pytest tests/benchmarks/test_resolve_scoped_with_registered_open_closed_generics_pair_same.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/resolve-scoped-open-closed-generics-pair-same.json" -q
    uv run pytest tests/benchmarks/test_resolve_scoped_with_registered_open_closed_generics_pair_alternating.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/resolve-scoped-open-closed-generics-pair-alternating.json" -q
    uv run pytest tests/benchmarks/test_resolve_mixed_lifetimes.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/resolve-mixed-lifetimes.json" -q
    uv run pytest tests/benchmarks/test_resolve_generated_scoped_grid.py --benchmark-only --benchmark-columns=ops --benchmark-json="$BENCHMARK_ARTIFACT_DIR/resolve-generated-scoped-grid.json" -q

benchmark-json: benchmark-artifact-dir
    uv run pytest tests/benchmarks --benchmark-only -q --benchmark-json="$BENCHMARK_ARTIFACT_DIR/all.json"

benchmark-report: benchmark-json
    uv run python -m tools.benchmark_reporting --input "$BENCHMARK_ARTIFACT_DIR/all.json" --markdown "$BENCHMARK_ARTIFACT_DIR/benchmark-table.md" --json "$BENCHMARK_ARTIFACT_DIR/benchmark-table.json" --comment "$BENCHMARK_ARTIFACT_DIR/pr-comment.md" --libraries diwire,rodi,dishka,wireup

benchmark-report-all: benchmark-json
    uv run python -m tools.benchmark_reporting --input "$BENCHMARK_ARTIFACT_DIR/all.json" --markdown "$BENCHMARK_ARTIFACT_DIR/benchmark-table-all.md" --json "$BENCHMARK_ARTIFACT_DIR/benchmark-table-all.json" --comment "$BENCHMARK_ARTIFACT_DIR/pr-comment-all.md" --libraries diwire,rodi,dishka,wireup

benchmark-json-resolve: benchmark-artifact-dir
    uv run pytest tests/benchmarks/test_resolve_transient.py tests/benchmarks/test_resolve_open_generic_transient.py tests/benchmarks/test_resolve_singleton.py tests/benchmarks/test_resolve_deep_transient_chain.py tests/benchmarks/test_resolve_wide_transient_graph.py tests/benchmarks/test_resolve_scoped_with_registered_open_closed_generics.py tests/benchmarks/test_resolve_scoped_with_registered_open_closed_generics_pair_same.py tests/benchmarks/test_resolve_scoped_with_registered_open_closed_generics_pair_alternating.py tests/benchmarks/test_resolve_generated_scoped_grid.py --benchmark-only -q --benchmark-json="$BENCHMARK_ARTIFACT_DIR/resolve.json"

benchmark-report-resolve: benchmark-json-resolve
    uv run python -m tools.benchmark_reporting --input "$BENCHMARK_ARTIFACT_DIR/resolve.json" --markdown "$BENCHMARK_ARTIFACT_DIR/benchmark-table-resolve.md" --json "$BENCHMARK_ARTIFACT_DIR/benchmark-table-resolve.json" --comment "$BENCHMARK_ARTIFACT_DIR/pr-comment-resolve.md" --libraries diwire,rodi,dishka,wireup
