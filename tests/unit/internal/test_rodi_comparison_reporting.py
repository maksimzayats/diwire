from __future__ import annotations

import itertools

import pytest

from tests.benchmarks.rodi_comparison import (
    CASES,
    CONCURRENCY_MODES,
    LIFETIMES,
    PROVIDERS,
    BenchmarkScenario,
    build_benchmark_matrix,
    create_result,
    render_markdown_table,
)


def test_build_benchmark_matrix_contains_all_case_provider_lifetime_combinations() -> None:
    matrix = build_benchmark_matrix()
    observed = {
        (
            scenario.case,
            scenario.provider,
            scenario.lifetime,
            scenario.diwire_concurrency_safe,
        )
        for scenario in matrix
    }
    expected = set(itertools.product(CASES, PROVIDERS, LIFETIMES, CONCURRENCY_MODES))

    assert len(matrix) == 54
    assert observed == expected


def test_render_markdown_table_has_expected_columns_and_is_deterministic() -> None:
    first = create_result(
        BenchmarkScenario(
            case="open_scope_plus_100_resolves",
            provider="concrete",
            lifetime="transient",
            diwire_concurrency_safe="disabled",
        ),
        diwire_seconds=0.002,
        rodi_seconds=0.003,
        iterations=100,
    )
    second = create_result(
        BenchmarkScenario(
            case="open_scope",
            provider="factory",
            lifetime="singleton",
            diwire_concurrency_safe="enabled",
        ),
        diwire_seconds=0.001,
        rodi_seconds=0.002,
        iterations=100,
    )

    markdown = render_markdown_table([first, second]).strip().splitlines()

    assert markdown[0] == (
        "Legend: Scenario describes scope operations; provider registration describes how the target service is registered."
    )
    assert markdown[1] == (
        "Legend: Resolves/Scope is the number of resolve calls executed inside each opened scope."
    )
    assert markdown[2] == ""
    assert markdown[3] == (
        "| Scenario | Resolves/Scope | Provider Registration | Lifetime | "
        "DIWire Concurrency Safe | DIWire (us/op) | Rodi (us/op) | Rodi/DIWire | Winner |"
    )
    assert markdown[4] == "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | --- |"
    assert markdown[5].startswith(
        "| Scope open/close only | 0 | Factory provider | singleton | enabled |",
    )
    assert markdown[6].startswith(
        "| Scope open/close + 100 resolves | 100 | Concrete provider | transient | disabled |",
    )


def test_create_result_computes_ratio_and_winner_from_known_values() -> None:
    faster = create_result(
        BenchmarkScenario(
            case="open_scope_plus_1_resolve",
            provider="concrete_with_dep",
            lifetime="scoped",
            diwire_concurrency_safe="enabled",
        ),
        diwire_seconds=0.001,
        rodi_seconds=0.002,
        iterations=100,
    )
    tie = create_result(
        BenchmarkScenario(
            case="open_scope",
            provider="factory",
            lifetime="transient",
            diwire_concurrency_safe="disabled",
        ),
        diwire_seconds=0.0015,
        rodi_seconds=0.0015,
        iterations=100,
    )

    assert faster.diwire_us_per_op == pytest.approx(10.0)
    assert faster.rodi_us_per_op == pytest.approx(20.0)
    assert faster.ratio_rodi_over_diwire == pytest.approx(2.0)
    assert faster.winner == "DIWire"
    assert tie.winner == "Tie"
