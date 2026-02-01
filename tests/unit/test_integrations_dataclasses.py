"""Tests for dataclasses integration."""

from dataclasses import dataclass, make_dataclass
from typing import Any

from diwire.container import Container


class DepService:
    pass


@dataclass
class DataclassModelWithDep:
    dep: DepService


@dataclass
class NestedDataclassModel:
    model: DataclassModelWithDep


@dataclass
class DataclassModelWithDefault:
    dep: DepService
    name: str = "default"


@dataclass
class EmptyDataclassModel:
    pass


class TestDataclassResolution:
    def test_resolve_dataclass_with_dependency(self, container: Container) -> None:
        """Dataclass with a dependency field resolves correctly."""
        result = container.resolve(DataclassModelWithDep)

        assert isinstance(result, DataclassModelWithDep)
        assert isinstance(result.dep, DepService)

    def test_resolve_empty_dataclass(self, container: Container) -> None:
        """Dataclass with no fields resolves correctly."""
        result = container.resolve(EmptyDataclassModel)

        assert isinstance(result, EmptyDataclassModel)

    def test_resolve_dataclass_with_default(self, container: Container) -> None:
        """Dataclass with default values resolves correctly."""
        result = container.resolve(DataclassModelWithDefault)

        assert isinstance(result, DataclassModelWithDefault)
        assert isinstance(result.dep, DepService)
        assert result.name == "default"

    def test_resolve_nested_dataclasses(self, container: Container) -> None:
        """Nested dataclass dependency chain resolves correctly."""
        result = container.resolve(NestedDataclassModel)

        assert isinstance(result, NestedDataclassModel)
        assert isinstance(result.model, DataclassModelWithDep)
        assert isinstance(result.model.dep, DepService)

    def test_resolve_make_dataclass(self, container: Container) -> None:
        """dataclasses.make_dataclass classes resolve correctly."""
        dynamic_model = make_dataclass(
            "DynamicModel",
            [("dep", DepService), ("name", str, "default")],
        )

        result: Any = container.resolve(dynamic_model)

        assert isinstance(result, dynamic_model)
        result_any: Any = result
        assert isinstance(result_any.dep, DepService)
        assert result_any.name == "default"
