from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, make_dataclass
from typing import Any

import rodi
from dishka import Provider
from wireup import injectable

from diwire import Container, Lifetime, Scope
from tests.benchmarks.dishka_helpers import DishkaBenchmarkScope, make_dishka_benchmark_container
from tests.benchmarks.helpers import make_diwire_benchmark_container, run_benchmark
from tests.benchmarks.wireup_helpers import make_wireup_benchmark_container

# Wireup container compilation time becomes pathological with larger generated graphs.
# Keep this scenario large enough to exercise scoped graph behavior while remaining runnable across frameworks.
GRID_WIDTH = 6
GRID_HEIGHT = 6


@dataclass(frozen=True, slots=True)
class _GridGraph:
    tops: tuple[type[Any], ...]
    layers: tuple[tuple[type[Any], ...], ...]
    bottom: type[Any]


def _make_node_class(name: str, deps: Sequence[type[Any]]) -> type[Any]:
    return make_dataclass(
        name,
        [(f"d_{index}", dep) for index, dep in enumerate(deps)],
        slots=True,
        namespace={"__module__": __name__},
    )


def _build_scoped_grid_graph(*, width: int, height: int) -> _GridGraph:
    tops = tuple(_make_node_class(f"_Top_{index}", ()) for index in range(width))
    layers: list[tuple[type[Any], ...]] = []

    prev_classes: tuple[type[Any], ...] = tops
    for level in range(height):
        layer = tuple(
            _make_node_class(f"_Middle_{level}_{index}", prev_classes) for index in range(width)
        )
        layers.append(layer)
        prev_classes = layer

    bottom = _make_node_class("_Bottom", prev_classes)
    return _GridGraph(
        tops=tops,
        layers=tuple(layers),
        bottom=bottom,
    )


def _build_scoped_grid_diwire_container(*, graph: _GridGraph) -> Container:
    container = make_diwire_benchmark_container()

    for cls in graph.tops:
        container.add(cls, lifetime=Lifetime.SCOPED, scope=Scope.APP)
    for layer in graph.layers:
        for cls in layer:
            container.add(cls, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    container.add(graph.bottom, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)
    container.compile()
    return container


def _build_scoped_grid_dishka_container(*, graph: _GridGraph) -> Any:
    provider = Provider(scope=DishkaBenchmarkScope.APP)

    for cls in graph.tops:
        provider.provide(cls, scope=DishkaBenchmarkScope.APP)
    for layer in graph.layers:
        for cls in layer:
            provider.provide(cls, scope=DishkaBenchmarkScope.REQUEST)
    provider.provide(graph.bottom, scope=DishkaBenchmarkScope.REQUEST)
    return make_dishka_benchmark_container(provider)


def _build_scoped_grid_rodi_container(*, graph: _GridGraph) -> Any:
    container = rodi.Container()

    for cls in graph.tops:
        container.add_singleton(cls)
    for layer in graph.layers:
        for cls in layer:
            container.add_scoped(cls)
    container.add_scoped(graph.bottom)
    return container.build_provider()


def _wireup_injectable(cls: type[Any], *, lifetime: str) -> type[Any]:
    return injectable(lifetime=lifetime)(cls)


def _build_scoped_grid_wireup_container(*, graph: _GridGraph) -> Any:
    injectables = [_wireup_injectable(cls, lifetime="singleton") for cls in graph.tops]
    for layer in graph.layers:
        injectables.extend(_wireup_injectable(cls, lifetime="scoped") for cls in layer)
    injectables.append(_wireup_injectable(graph.bottom, lifetime="scoped"))

    return make_wireup_benchmark_container(*injectables)


def _walk_to_top(node: Any, *, height: int) -> Any:
    current = node.d_0
    for _ in range(height):
        current = current.d_0
    return current


def test_benchmark_diwire_resolve_generated_scoped_grid(benchmark: Any) -> None:
    graph = _build_scoped_grid_graph(width=GRID_WIDTH, height=GRID_HEIGHT)
    container = _build_scoped_grid_diwire_container(graph=graph)

    with container.enter_scope(Scope.REQUEST) as first_scope:
        first = first_scope.resolve(graph.bottom)
        second = first_scope.resolve(graph.bottom)
    with container.enter_scope(Scope.REQUEST) as second_scope:
        third = second_scope.resolve(graph.bottom)

    assert first is second
    assert first is not third
    assert first.d_0 is not third.d_0

    first_top = _walk_to_top(first, height=GRID_HEIGHT)
    third_top = _walk_to_top(third, height=GRID_HEIGHT)
    assert first_top is third_top

    def bench_diwire_generated_scoped_grid() -> None:
        with container.enter_scope(Scope.REQUEST) as scope:
            _ = scope.resolve(graph.bottom)

    run_benchmark(benchmark, bench_diwire_generated_scoped_grid, iterations=500)


def test_benchmark_dishka_resolve_generated_scoped_grid(benchmark: Any) -> None:
    graph = _build_scoped_grid_graph(width=GRID_WIDTH, height=GRID_HEIGHT)
    container = _build_scoped_grid_dishka_container(graph=graph)

    with container(scope=DishkaBenchmarkScope.REQUEST) as first_scope:
        first = first_scope.get(graph.bottom)
        second = first_scope.get(graph.bottom)
    with container(scope=DishkaBenchmarkScope.REQUEST) as second_scope:
        third = second_scope.get(graph.bottom)

    assert first is second
    assert first is not third
    assert first.d_0 is not third.d_0

    first_top = _walk_to_top(first, height=GRID_HEIGHT)
    third_top = _walk_to_top(third, height=GRID_HEIGHT)
    assert first_top is third_top

    def bench_dishka_generated_scoped_grid() -> None:
        with container(scope=DishkaBenchmarkScope.REQUEST) as scope:
            _ = scope.get(graph.bottom)

    run_benchmark(benchmark, bench_dishka_generated_scoped_grid, iterations=500)


def test_benchmark_rodi_resolve_generated_scoped_grid(benchmark: Any) -> None:
    graph = _build_scoped_grid_graph(width=GRID_WIDTH, height=GRID_HEIGHT)
    container = _build_scoped_grid_rodi_container(graph=graph)

    with container.create_scope() as first_scope:
        first = first_scope.get(graph.bottom)
        second = first_scope.get(graph.bottom)
    with container.create_scope() as second_scope:
        third = second_scope.get(graph.bottom)

    assert first is second
    assert first is not third
    assert first.d_0 is not third.d_0

    first_top = _walk_to_top(first, height=GRID_HEIGHT)
    third_top = _walk_to_top(third, height=GRID_HEIGHT)
    assert first_top is third_top

    def bench_rodi_generated_scoped_grid() -> None:
        with container.create_scope() as scope:
            _ = scope.get(graph.bottom)

    run_benchmark(benchmark, bench_rodi_generated_scoped_grid, iterations=500)


def test_benchmark_wireup_resolve_generated_scoped_grid(benchmark: Any) -> None:
    graph = _build_scoped_grid_graph(width=GRID_WIDTH, height=GRID_HEIGHT)
    container = _build_scoped_grid_wireup_container(graph=graph)

    with container.enter_scope() as first_scope:
        first = first_scope.get(graph.bottom)
        second = first_scope.get(graph.bottom)
    with container.enter_scope() as second_scope:
        third = second_scope.get(graph.bottom)

    assert first is second
    assert first is not third
    assert first.d_0 is not third.d_0

    first_top = _walk_to_top(first, height=GRID_HEIGHT)
    third_top = _walk_to_top(third, height=GRID_HEIGHT)
    assert first_top is third_top

    def bench_wireup_generated_scoped_grid() -> None:
        with container.enter_scope() as scope:
            _ = scope.get(graph.bottom)

    run_benchmark(benchmark, bench_wireup_generated_scoped_grid, iterations=500)
