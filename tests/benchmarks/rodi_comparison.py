from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Final, Literal, TypeAlias

import rodi

from diwire.container import Container as DIWireContainer
from diwire.providers import Lifetime
from diwire.scope import Scope

CaseName: TypeAlias = Literal[
    "open_scope",
    "open_scope_plus_1_resolve",
    "open_scope_plus_100_resolves",
]
ProviderName: TypeAlias = Literal["factory", "concrete", "concrete_with_dep"]
LifetimeName: TypeAlias = Literal["singleton", "scoped", "transient"]
WinnerName: TypeAlias = Literal["DIWire", "rodi", "Tie"]
ConcurrencyName: TypeAlias = Literal["enabled", "disabled"]

CASES: Final[tuple[CaseName, ...]] = (
    "open_scope",
    "open_scope_plus_1_resolve",
    "open_scope_plus_100_resolves",
)
PROVIDERS: Final[tuple[ProviderName, ...]] = ("factory", "concrete", "concrete_with_dep")
LIFETIMES: Final[tuple[LifetimeName, ...]] = ("singleton", "scoped", "transient")
CONCURRENCY_MODES: Final[tuple[ConcurrencyName, ...]] = ("enabled", "disabled")

CASE_LABELS: Final[dict[CaseName, str]] = {
    "open_scope": "Scope open/close only",
    "open_scope_plus_1_resolve": "Scope open/close + 1 resolve",
    "open_scope_plus_100_resolves": "Scope open/close + 100 resolves",
}

PROVIDER_LABELS: Final[dict[ProviderName, str]] = {
    "factory": "Factory provider",
    "concrete": "Concrete provider",
    "concrete_with_dep": "Concrete provider (+1 dependency)",
}

CASE_RESOLVE_COUNTS: Final[dict[CaseName, int]] = {
    "open_scope": 0,
    "open_scope_plus_1_resolve": 1,
    "open_scope_plus_100_resolves": 100,
}

DEFAULT_ITERATIONS_BY_CASE: Final[dict[CaseName, int]] = {
    "open_scope": 50_000,
    "open_scope_plus_1_resolve": 15_000,
    "open_scope_plus_100_resolves": 1_000,
}
DEFAULT_WARMUP_ROUNDS: Final[int] = 2
DEFAULT_MEASURE_ROUNDS: Final[int] = 5
DEFAULT_OUTPUT_MARKDOWN: Final[Path] = Path(".benchmarks/rodi-comparison.md")
DEFAULT_OUTPUT_JSON: Final[Path] = Path(".benchmarks/rodi-comparison.json")
MICROSECONDS_IN_SECOND: Final[float] = 1_000_000.0


class _FactoryService:
    pass


class _ConcreteService:
    pass


class _DependencyService:
    pass


class _ConcreteWithDependencyService:
    def __init__(self, dependency: _DependencyService) -> None:
        self.dependency = dependency


def _build_factory_service() -> _FactoryService:
    return _FactoryService()


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    case: CaseName
    provider: ProviderName
    lifetime: LifetimeName
    diwire_concurrency_safe: ConcurrencyName


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    case: CaseName
    provider: ProviderName
    lifetime: LifetimeName
    diwire_concurrency_safe: ConcurrencyName
    diwire_us_per_op: float
    rodi_us_per_op: float
    ratio_rodi_over_diwire: float
    winner: WinnerName


@dataclass(frozen=True, slots=True)
class BenchmarkRunConfig:
    warmup_rounds: int
    measure_rounds: int
    iterations_by_case: dict[CaseName, int]
    output_markdown: Path
    output_json: Path


def build_benchmark_matrix() -> list[BenchmarkScenario]:
    return [
        BenchmarkScenario(
            case=case,
            provider=provider,
            lifetime=lifetime,
            diwire_concurrency_safe=diwire_concurrency_safe,
        )
        for case in CASES
        for provider in PROVIDERS
        for lifetime in LIFETIMES
        for diwire_concurrency_safe in CONCURRENCY_MODES
    ]


def create_result(
    scenario: BenchmarkScenario,
    *,
    diwire_seconds: float,
    rodi_seconds: float,
    iterations: int,
) -> BenchmarkResult:
    diwire_us_per_op = (diwire_seconds / iterations) * MICROSECONDS_IN_SECOND
    rodi_us_per_op = (rodi_seconds / iterations) * MICROSECONDS_IN_SECOND

    if diwire_us_per_op == rodi_us_per_op:
        winner: WinnerName = "Tie"
    elif diwire_us_per_op < rodi_us_per_op:
        winner = "DIWire"
    else:
        winner = "rodi"

    ratio = float("inf") if diwire_us_per_op == 0.0 else rodi_us_per_op / diwire_us_per_op

    return BenchmarkResult(
        case=scenario.case,
        provider=scenario.provider,
        lifetime=scenario.lifetime,
        diwire_concurrency_safe=scenario.diwire_concurrency_safe,
        diwire_us_per_op=diwire_us_per_op,
        rodi_us_per_op=rodi_us_per_op,
        ratio_rodi_over_diwire=ratio,
        winner=winner,
    )


def _diwire_lifetime(lifetime: LifetimeName) -> Lifetime:
    if lifetime == "singleton":
        return Lifetime.SINGLETON
    if lifetime == "scoped":
        return Lifetime.SCOPED
    return Lifetime.TRANSIENT


def _diwire_scope(lifetime: LifetimeName) -> Any:
    if lifetime == "scoped":
        return Scope.REQUEST
    return None


def _configure_diwire_scenario(
    scenario: BenchmarkScenario,
) -> tuple[DIWireContainer, type[Any]]:
    container = DIWireContainer(
        default_concurrency_safe=scenario.diwire_concurrency_safe == "enabled",
    )
    lifetime = _diwire_lifetime(scenario.lifetime)
    scope = _diwire_scope(scenario.lifetime)

    if scenario.provider == "factory":
        container.register_factory(
            _FactoryService,
            factory=_build_factory_service,
            lifetime=lifetime,
            scope=scope,
        )
        return container, _FactoryService

    if scenario.provider == "concrete":
        container.register_concrete(
            concrete_type=_ConcreteService,
            lifetime=lifetime,
            scope=scope,
        )
        return container, _ConcreteService

    container.register_concrete(
        concrete_type=_DependencyService,
        lifetime=Lifetime.SINGLETON,
    )
    container.register_concrete(
        concrete_type=_ConcreteWithDependencyService,
        lifetime=lifetime,
        scope=scope,
    )
    return container, _ConcreteWithDependencyService


def _register_rodi_factory(
    container: rodi.Container,
    lifetime: LifetimeName,
) -> None:
    if lifetime == "singleton":
        container.add_singleton_by_factory(_build_factory_service, _FactoryService)
    elif lifetime == "scoped":
        container.add_scoped_by_factory(_build_factory_service, _FactoryService)
    else:
        container.add_transient_by_factory(_build_factory_service, _FactoryService)


def _register_rodi_concrete(
    container: rodi.Container,
    lifetime: LifetimeName,
    concrete_type: type[Any],
) -> None:
    if lifetime == "singleton":
        container.add_singleton(concrete_type)
    elif lifetime == "scoped":
        container.add_scoped(concrete_type)
    else:
        container.add_transient(concrete_type)


def _configure_rodi_scenario(
    scenario: BenchmarkScenario,
) -> tuple[Any, type[Any]]:
    container = rodi.Container()

    if scenario.provider == "factory":
        _register_rodi_factory(container, scenario.lifetime)
        return container.build_provider(), _FactoryService

    if scenario.provider == "concrete":
        _register_rodi_concrete(container, scenario.lifetime, _ConcreteService)
        return container.build_provider(), _ConcreteService

    container.add_singleton(_DependencyService)
    _register_rodi_concrete(container, scenario.lifetime, _ConcreteWithDependencyService)
    return container.build_provider(), _ConcreteWithDependencyService


def _warm_up_diwire(
    container: DIWireContainer,
    target_type: type[Any],
    resolve_count: int,
) -> None:
    with container.enter_scope() as scoped_container:
        for _ in range(resolve_count):
            scoped_container.resolve(target_type)


def _warm_up_rodi(services: Any, target_type: type[Any], resolve_count: int) -> None:
    with services.create_scope() as scoped_services:
        for _ in range(resolve_count):
            scoped_services.get(target_type)


def _build_diwire_operation(scenario: BenchmarkScenario) -> Callable[[], None]:
    container, target_type = _configure_diwire_scenario(scenario)
    resolve_count = CASE_RESOLVE_COUNTS[scenario.case]
    _warm_up_diwire(container, target_type, resolve_count)

    def operation() -> None:
        with container.enter_scope() as scoped_container:
            for _ in range(resolve_count):
                scoped_container.resolve(target_type)

    return operation


def _build_rodi_operation(scenario: BenchmarkScenario) -> Callable[[], None]:
    services, target_type = _configure_rodi_scenario(scenario)
    resolve_count = CASE_RESOLVE_COUNTS[scenario.case]
    _warm_up_rodi(services, target_type, resolve_count)

    def operation() -> None:
        with services.create_scope() as scoped_services:
            for _ in range(resolve_count):
                scoped_services.get(target_type)

    return operation


def _run_operation(operation: Callable[[], None], iterations: int) -> float:
    start = perf_counter()
    for _ in range(iterations):
        operation()
    return perf_counter() - start


def measure_scenario(scenario: BenchmarkScenario, config: BenchmarkRunConfig) -> BenchmarkResult:
    diwire_operation = _build_diwire_operation(scenario)
    rodi_operation = _build_rodi_operation(scenario)
    iterations = config.iterations_by_case[scenario.case]

    for round_index in range(config.warmup_rounds):
        if round_index % 2 == 0:
            _run_operation(diwire_operation, iterations)
            _run_operation(rodi_operation, iterations)
        else:
            _run_operation(rodi_operation, iterations)
            _run_operation(diwire_operation, iterations)

    diwire_samples: list[float] = []
    rodi_samples: list[float] = []

    for round_index in range(config.measure_rounds):
        if round_index % 2 == 0:
            diwire_samples.append(_run_operation(diwire_operation, iterations))
            rodi_samples.append(_run_operation(rodi_operation, iterations))
        else:
            rodi_samples.append(_run_operation(rodi_operation, iterations))
            diwire_samples.append(_run_operation(diwire_operation, iterations))

    return create_result(
        scenario,
        diwire_seconds=median(diwire_samples),
        rodi_seconds=median(rodi_samples),
        iterations=iterations,
    )


def run_comparison(config: BenchmarkRunConfig) -> list[BenchmarkResult]:
    return [measure_scenario(scenario, config) for scenario in build_benchmark_matrix()]


def _sort_key(result: BenchmarkResult) -> tuple[int, int, int, int]:
    case_order = {case: index for index, case in enumerate(CASES)}
    provider_order = {provider: index for index, provider in enumerate(PROVIDERS)}
    lifetime_order = {lifetime: index for index, lifetime in enumerate(LIFETIMES)}
    concurrency_order = {concurrency: index for index, concurrency in enumerate(CONCURRENCY_MODES)}
    return (
        case_order[result.case],
        provider_order[result.provider],
        lifetime_order[result.lifetime],
        concurrency_order[result.diwire_concurrency_safe],
    )


def sort_results(results: Sequence[BenchmarkResult]) -> list[BenchmarkResult]:
    return sorted(results, key=_sort_key)


def render_markdown_table(results: Sequence[BenchmarkResult]) -> str:
    lines = [
        "Legend: Scenario describes scope operations; provider registration describes how the target service is registered.",
        "Legend: Resolves/Scope is the number of resolve calls executed inside each opened scope.",
        "",
        (
            "| Scenario | Resolves/Scope | Provider Registration | Lifetime | "
            "DIWire Concurrency Safe | DIWire (us/op) | Rodi (us/op) | Rodi/DIWire | Winner |"
        ),
        "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    lines.extend(
        "| "
        f"{CASE_LABELS[result.case]} | "
        f"{CASE_RESOLVE_COUNTS[result.case]} | "
        f"{PROVIDER_LABELS[result.provider]} | "
        f"{result.lifetime} | "
        f"{result.diwire_concurrency_safe} | "
        f"{result.diwire_us_per_op:.3f} | "
        f"{result.rodi_us_per_op:.3f} | "
        f"{result.ratio_rodi_over_diwire:.3f} | "
        f"{result.winner} |"
        for result in sort_results(results)
    )
    return "\n".join(lines) + "\n"


def write_outputs(
    results: Sequence[BenchmarkResult],
    *,
    output_markdown: Path,
    output_json: Path,
) -> None:
    sorted_results = sort_results(results)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.write_text(render_markdown_table(sorted_results), encoding="utf-8")
    output_json.write_text(
        json.dumps([asdict(result) for result in sorted_results], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_config_from_args(args: argparse.Namespace) -> BenchmarkRunConfig:
    iterations_by_case: dict[CaseName, int] = {
        "open_scope": args.open_scope_iterations,
        "open_scope_plus_1_resolve": args.open_scope_plus_1_resolve_iterations,
        "open_scope_plus_100_resolves": args.open_scope_plus_100_resolves_iterations,
    }
    return BenchmarkRunConfig(
        warmup_rounds=args.warmup_rounds,
        measure_rounds=args.measure_rounds,
        iterations_by_case=iterations_by_case,
        output_markdown=Path(args.output_markdown),
        output_json=Path(args.output_json),
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run DIWire vs rodi benchmarks and output markdown + json reports.",
    )
    parser.add_argument("--output-markdown", default=str(DEFAULT_OUTPUT_MARKDOWN))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--warmup-rounds", type=int, default=DEFAULT_WARMUP_ROUNDS)
    parser.add_argument("--measure-rounds", type=int, default=DEFAULT_MEASURE_ROUNDS)
    parser.add_argument(
        "--open-scope-iterations",
        type=int,
        default=DEFAULT_ITERATIONS_BY_CASE["open_scope"],
    )
    parser.add_argument(
        "--open-scope-plus-1-resolve-iterations",
        type=int,
        default=DEFAULT_ITERATIONS_BY_CASE["open_scope_plus_1_resolve"],
    )
    parser.add_argument(
        "--open-scope-plus-100-resolves-iterations",
        type=int,
        default=DEFAULT_ITERATIONS_BY_CASE["open_scope_plus_100_resolves"],
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = _build_config_from_args(args)
    results = run_comparison(config)
    write_outputs(
        results,
        output_markdown=config.output_markdown,
        output_json=config.output_json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
