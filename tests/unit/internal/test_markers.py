from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Protocol, TypeAlias, get_args, get_origin

from diwire.container import Container
from diwire.markers import Component, Injected, InjectedMarker
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
    container.register_factory(factory=build_primary)
    container.register_factory(factory=build_replica)

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
    container.register_factory(factory=build_primary)
    container.register_factory(factory=build_replica)
    container.register_concrete(concrete_type=Repository)

    repository = container.resolve(Repository)

    assert isinstance(repository.primary, PrimaryDatabase)
    assert isinstance(repository.replica, ReplicaDatabase)
