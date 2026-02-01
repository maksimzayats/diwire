"""Tests for attrs integration."""

import attrs

from diwire.container import Container


class DepService:
    pass


@attrs.define
class AttrsModelWithDep:
    dep: DepService


@attrs.define
class NestedAttrsModel:
    model: AttrsModelWithDep


@attrs.define
class AttrsModelWithDefault:
    dep: DepService
    name: str = "default"


@attrs.define
class EmptyAttrsModel:
    pass


class TestAttrsResolution:
    def test_resolve_attrs_model_with_dependency(self, container: Container) -> None:
        """Attrs model with a dependency field resolves correctly."""
        result = container.resolve(AttrsModelWithDep)

        assert isinstance(result, AttrsModelWithDep)
        assert isinstance(result.dep, DepService)

    def test_resolve_empty_attrs_model(self, container: Container) -> None:
        """Attrs model with no fields resolves correctly."""
        result = container.resolve(EmptyAttrsModel)

        assert isinstance(result, EmptyAttrsModel)

    def test_resolve_attrs_model_with_default(self, container: Container) -> None:
        """Attrs model with default values resolves correctly."""
        result = container.resolve(AttrsModelWithDefault)

        assert isinstance(result, AttrsModelWithDefault)
        assert isinstance(result.dep, DepService)
        assert result.name == "default"

    def test_resolve_nested_attrs_models(self, container: Container) -> None:
        """Nested attrs model dependency chain resolves correctly."""
        result = container.resolve(NestedAttrsModel)

        assert isinstance(result, NestedAttrsModel)
        assert isinstance(result.model, AttrsModelWithDep)
        assert isinstance(result.model.dep, DepService)

    def test_resolve_regular_class_depending_on_attrs(self, container: Container) -> None:
        """Regular class depending on attrs model resolves correctly."""

        class RegularDependent:
            def __init__(self, model: AttrsModelWithDep) -> None:
                self.model = model

        result = container.resolve(RegularDependent)

        assert isinstance(result, RegularDependent)
        assert isinstance(result.model, AttrsModelWithDep)
        assert isinstance(result.model.dep, DepService)
