from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Protocol, TypeAlias, get_args, get_origin

import pytest

import diwire.markers as markers_module
from diwire.container import Container
from diwire.markers import (
    Component,
    FromContext,
    FromContextMarker,
    Injected,
    InjectedMarker,
    is_from_context_annotation,
    strip_from_context_annotation,
)
from diwire.providers import ProviderDependenciesExtractor


class Database(Protocol):
    def query(self) -> str: ...


PrimaryDatabaseComponent: TypeAlias = Annotated[Database, Component("primary")]
ReplicaDatabaseComponent: TypeAlias = Annotated[Database, Component("replica")]


@dataclass
class PrimaryDatabase:
    def query(self) -> str:
        return "primary"


@dataclass
class ReplicaDatabase:
    def query(self) -> str:
        return "replica"


@dataclass
class Repository:
    primary: PrimaryDatabaseComponent
    replica: ReplicaDatabaseComponent


def test_component_marker_is_value_based_and_hashable() -> None:
    marker = Component("primary")

    assert marker.value == "primary"
    assert marker == Component("primary")
    assert marker != Component("replica")

    mapping = {marker: "database"}
    assert mapping[Component("primary")] == "database"


def test_provider_dependencies_extractor_preserves_component_marker() -> None:
    def build_repository(primary: PrimaryDatabaseComponent) -> Repository:
        return Repository(primary=primary, replica=ReplicaDatabase())

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_factory(build_repository)

    assert [dependency.parameter.name for dependency in dependencies] == ["primary"]
    assert [dependency.provides for dependency in dependencies] == [PrimaryDatabaseComponent]


def test_injected_wraps_dependency_with_injected_marker() -> None:
    dependency = Injected[Database]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert isinstance(annotation_args[1], InjectedMarker)


def test_injected_preserves_component_marker_metadata_when_nested() -> None:
    dependency = Injected[PrimaryDatabaseComponent]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert annotation_args[1] == Component("primary")
    assert isinstance(annotation_args[2], InjectedMarker)


def test_from_context_wraps_dependency_with_marker() -> None:
    dependency = FromContext[Database]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert isinstance(annotation_args[1], FromContextMarker)


def test_from_context_preserves_component_marker_metadata_when_nested() -> None:
    dependency = FromContext[PrimaryDatabaseComponent]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert annotation_args[1] == Component("primary")
    assert isinstance(annotation_args[2], FromContextMarker)


def test_from_context_helpers_detect_and_strip_marker() -> None:
    dependency = FromContext[PrimaryDatabaseComponent]

    assert is_from_context_annotation(dependency) is True
    assert strip_from_context_annotation(dependency) == PrimaryDatabaseComponent
    assert is_from_context_annotation(int) is False
    assert strip_from_context_annotation(int) is int


def test_is_from_context_annotation_handles_invalid_annotated_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(markers_module, "get_origin", lambda _annotation: Annotated)
    monkeypatch.setattr(markers_module, "get_args", lambda _annotation: (int,))

    assert markers_module.is_from_context_annotation(object()) is False


def test_provider_dependencies_extractor_preserves_injected_component_dependency() -> None:
    def build_repository(primary: Injected[PrimaryDatabaseComponent]) -> Repository:
        return Repository(primary=primary, replica=ReplicaDatabase())

    extractor = ProviderDependenciesExtractor()

    dependencies = extractor.extract_from_factory(build_repository)

    assert [dependency.parameter.name for dependency in dependencies] == ["primary"]
    annotation_args = get_args(dependencies[0].provides)
    assert len(annotation_args) == 3
    assert annotation_args[0] is Database
    assert annotation_args[1] == Component("primary")
    assert isinstance(annotation_args[2], InjectedMarker)


def test_container_resolves_distinct_component_registrations() -> None:
    def build_primary() -> PrimaryDatabaseComponent:
        return PrimaryDatabase()

    def build_replica() -> ReplicaDatabaseComponent:
        return ReplicaDatabase()

    container = Container()
    container.add_factory(build_primary)
    container.add_factory(build_replica)

    primary = container.resolve(PrimaryDatabaseComponent)
    replica = container.resolve(ReplicaDatabaseComponent)

    assert isinstance(primary, PrimaryDatabase)
    assert isinstance(replica, ReplicaDatabase)
    assert primary.query() == "primary"
    assert replica.query() == "replica"


def test_container_injects_component_marked_dependencies() -> None:
    def build_primary() -> PrimaryDatabaseComponent:
        return PrimaryDatabase()

    def build_replica() -> ReplicaDatabaseComponent:
        return ReplicaDatabase()

    container = Container()
    container.add_factory(build_primary)
    container.add_factory(build_replica)
    container.add_concrete(Repository)

    repository = container.resolve(Repository)

    assert isinstance(repository.primary, PrimaryDatabase)
    assert isinstance(repository.replica, ReplicaDatabase)
