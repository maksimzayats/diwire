"""Tests for NamedTuple integration."""

import collections
from typing import NamedTuple

from diwire.container import Container


class DepService:
    pass


class NamedTupleModelWithDep(NamedTuple):
    dep: DepService


class NestedNamedTupleModel(NamedTuple):
    model: NamedTupleModelWithDep


class NamedTupleModelWithDefault(NamedTuple):
    dep: DepService
    name: str = "default"


class EmptyNamedTupleModel(NamedTuple):
    pass


class TestNamedTupleResolution:
    def test_resolve_namedtuple_with_dependency(self, container: Container) -> None:
        """NamedTuple with a dependency field resolves correctly."""
        result = container.resolve(NamedTupleModelWithDep)

        assert isinstance(result, NamedTupleModelWithDep)
        assert isinstance(result.dep, DepService)

    def test_resolve_empty_namedtuple(self, container: Container) -> None:
        """NamedTuple with no fields resolves correctly."""
        result = container.resolve(EmptyNamedTupleModel)

        assert isinstance(result, EmptyNamedTupleModel)

    def test_resolve_namedtuple_with_default(self, container: Container) -> None:
        """NamedTuple with default values resolves correctly."""
        result = container.resolve(NamedTupleModelWithDefault)

        assert isinstance(result, NamedTupleModelWithDefault)
        assert isinstance(result.dep, DepService)
        assert result.name == "default"

    def test_resolve_nested_namedtuples(self, container: Container) -> None:
        """Nested NamedTuple dependency chain resolves correctly."""
        result = container.resolve(NestedNamedTupleModel)

        assert isinstance(result, NestedNamedTupleModel)
        assert isinstance(result.model, NamedTupleModelWithDep)
        assert isinstance(result.model.dep, DepService)

    def test_resolve_regular_class_depending_on_namedtuple(
        self,
        container: Container,
    ) -> None:
        """Regular class depending on NamedTuple resolves correctly."""

        class RegularDependent:
            def __init__(self, model: NamedTupleModelWithDep) -> None:
                self.model = model

        result = container.resolve(RegularDependent)

        assert isinstance(result, RegularDependent)
        assert isinstance(result.model, NamedTupleModelWithDep)
        assert isinstance(result.model.dep, DepService)

    def test_resolve_collections_namedtuple(self, container: Container) -> None:
        """collections.namedtuple classes resolve correctly."""
        legacy_tuple = collections.namedtuple("legacy_tuple", ["dep"])  # noqa: PYI024
        legacy_tuple.__annotations__ = {"dep": DepService}

        result = container.resolve(legacy_tuple)

        assert isinstance(result, legacy_tuple)
        assert isinstance(result.dep, DepService)
