from __future__ import annotations

from punq import Container as PunqContainer
from pytest_benchmark.fixture import BenchmarkFixture
from rodi import Container as RodiContainer

from diwire import Container
from tests.benchmarks.shared import (
    ChainDep1,
    ChainDep2,
    ChainDep3,
    ChainDep4,
    ChainDep5,
    ChainDep6,
    ChainDep7,
    ChainDep8,
    ChainDep9,
    ChainDep10,
    ChainGraphRoot,
)

CHAIN_DEPENDENCIES = (
    ChainDep1,
    ChainDep2,
    ChainDep3,
    ChainDep4,
    ChainDep5,
    ChainDep6,
    ChainDep7,
    ChainDep8,
    ChainDep9,
    ChainDep10,
)


def test_diwire_transient_chain_resolution(benchmark: BenchmarkFixture) -> None:
    container = Container()

    first = container.resolve(ChainGraphRoot)
    container.compile()
    result = benchmark(container.resolve, ChainGraphRoot)

    assert result is not first


def test_punq_transient_chain_resolution(benchmark: BenchmarkFixture) -> None:
    container = PunqContainer()
    for dependency in CHAIN_DEPENDENCIES:
        container.register(dependency)
    container.register(ChainGraphRoot)

    first = container.resolve(ChainGraphRoot)
    result = benchmark(container.resolve, ChainGraphRoot)

    assert result is not first


def test_rodi_transient_chain_resolution(benchmark: BenchmarkFixture) -> None:
    container = RodiContainer()
    for dependency in CHAIN_DEPENDENCIES:
        container.register(dependency)
    container.register(ChainGraphRoot)

    first = container.resolve(ChainGraphRoot)
    result = benchmark(container.resolve, ChainGraphRoot)

    assert result is not first
