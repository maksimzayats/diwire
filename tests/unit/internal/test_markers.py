from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Protocol, TypeAlias, get_args, get_origin

import pytest

import diwire.markers as markers_module
from diwire.container import Container
from diwire.markers import (
    All,
    AllMarker,
    AsyncProvider,
    Component,
    FromContext,
    FromContextMarker,
    Injected,
    InjectedMarker,
    Maybe,
    MaybeMarker,
    Provider,
    ProviderMarker,
    component_base_key,
    is_all_annotation,
    is_async_provider_annotation,
    is_from_context_annotation,
    is_maybe_annotation,
    is_provider_annotation,
    strip_all_annotation,
    strip_from_context_annotation,
    strip_maybe_annotation,
    strip_provider_annotation,
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


def test_maybe_wraps_dependency_with_marker() -> None:
    dependency = Maybe[Database]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert isinstance(annotation_args[1], MaybeMarker)


def test_maybe_preserves_component_marker_metadata_when_nested() -> None:
    dependency = Maybe[PrimaryDatabaseComponent]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert annotation_args[1] == Component("primary")
    assert isinstance(annotation_args[2], MaybeMarker)


def test_maybe_helpers_detect_and_strip_marker() -> None:
    dependency = Maybe[PrimaryDatabaseComponent]

    assert is_maybe_annotation(dependency) is True
    assert strip_maybe_annotation(dependency) == PrimaryDatabaseComponent
    assert is_maybe_annotation(int) is False
    assert strip_maybe_annotation(int) is int


def test_provider_wraps_dependency_with_provider_marker() -> None:
    dependency = Provider[Database]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert isinstance(annotation_args[1], ProviderMarker)
    assert annotation_args[1].dependency_key is Database
    assert annotation_args[1].is_async is False


def test_async_provider_wraps_dependency_with_async_provider_marker() -> None:
    dependency = AsyncProvider[Database]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert isinstance(annotation_args[1], ProviderMarker)
    assert annotation_args[1].dependency_key is Database
    assert annotation_args[1].is_async is True


def test_provider_preserves_component_marker_metadata_when_nested() -> None:
    dependency = Provider[PrimaryDatabaseComponent]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert annotation_args[1] == Component("primary")
    assert isinstance(annotation_args[2], ProviderMarker)
    assert annotation_args[2].dependency_key == PrimaryDatabaseComponent


def test_provider_helpers_detect_strip_and_check_async_flags() -> None:
    sync_dependency = Provider[PrimaryDatabaseComponent]
    async_dependency = AsyncProvider[PrimaryDatabaseComponent]

    assert is_provider_annotation(sync_dependency) is True
    assert is_provider_annotation(async_dependency) is True
    assert strip_provider_annotation(sync_dependency) == PrimaryDatabaseComponent
    assert strip_provider_annotation(async_dependency) == PrimaryDatabaseComponent
    assert strip_provider_annotation(int) is int
    assert is_async_provider_annotation(sync_dependency) is False
    assert is_async_provider_annotation(async_dependency) is True
    assert is_async_provider_annotation(int) is False


def test_all_wraps_dependency_with_all_marker() -> None:
    dependency = All[Database]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert isinstance(annotation_args[1], AllMarker)
    assert annotation_args[1].dependency_key is Database


def test_all_strips_annotated_item_to_base_key() -> None:
    dependency = All[PrimaryDatabaseComponent]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert len(annotation_args) == 2
    assert isinstance(annotation_args[1], AllMarker)
    assert annotation_args[1].dependency_key is Database


def test_injected_all_preserves_all_marker_metadata_when_nested() -> None:
    dependency = Injected[All[Database]]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert isinstance(annotation_args[1], AllMarker)
    assert isinstance(annotation_args[2], InjectedMarker)


def test_all_helpers_detect_and_strip_marker() -> None:
    dependency = All[Database]

    assert is_all_annotation(dependency) is True
    assert strip_all_annotation(dependency) is Database
    assert is_all_annotation(int) is False
    assert strip_all_annotation(int) is int


def test_component_base_key_detects_component_keys() -> None:
    unrelated_annotated = Annotated[Database, "unrelated"]

    assert component_base_key(PrimaryDatabaseComponent) is Database
    assert component_base_key(Database) is None
    assert component_base_key(Injected[PrimaryDatabaseComponent]) is Database
    assert component_base_key(unrelated_annotated) is None


def test_injected_provider_preserves_provider_metadata() -> None:
    dependency = Injected[Provider[PrimaryDatabaseComponent]]

    assert get_origin(dependency) is Annotated
    annotation_args = get_args(dependency)
    assert annotation_args[0] is Database
    assert annotation_args[1] == Component("primary")
    assert isinstance(annotation_args[2], ProviderMarker)
    assert annotation_args[2].dependency_key == PrimaryDatabaseComponent
    assert isinstance(annotation_args[3], InjectedMarker)


def test_is_from_context_annotation_handles_invalid_annotated_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(markers_module, "get_origin", lambda _annotation: Annotated)
    monkeypatch.setattr(markers_module, "get_args", lambda _annotation: (int,))

    sentinel = object()

    assert markers_module.is_from_context_annotation(sentinel) is False
    assert markers_module.is_maybe_annotation(sentinel) is False
    assert markers_module.is_provider_annotation(sentinel) is False
    assert markers_module.is_all_annotation(sentinel) is False
    assert markers_module.strip_all_annotation(sentinel) is sentinel
    assert markers_module.strip_maybe_annotation(sentinel) is sentinel
    assert markers_module.component_base_key(sentinel) is None


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
