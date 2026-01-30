"""Tests for msgspec integration."""

import msgspec

from diwire.container import Container


class DepService:
    pass


class MsgspecModelWithDep(msgspec.Struct):
    dep: DepService


class NestedMsgspecModel(msgspec.Struct):
    model: MsgspecModelWithDep


class MsgspecModelWithDefault(msgspec.Struct):
    dep: DepService
    name: str = "default"


class EmptyMsgspecModel(msgspec.Struct):
    pass


class TestMsgspecResolution:
    def test_resolve_msgspec_model_with_dependency(self, container: Container) -> None:
        """Msgspec struct with a dependency field resolves correctly."""
        result = container.resolve(MsgspecModelWithDep)

        assert isinstance(result, MsgspecModelWithDep)
        assert isinstance(result.dep, DepService)

    def test_resolve_empty_msgspec_model(self, container: Container) -> None:
        """Msgspec struct with no fields resolves correctly."""
        result = container.resolve(EmptyMsgspecModel)

        assert isinstance(result, EmptyMsgspecModel)

    def test_resolve_msgspec_model_with_default(self, container: Container) -> None:
        """Msgspec struct with default values resolves correctly."""
        result = container.resolve(MsgspecModelWithDefault)

        assert isinstance(result, MsgspecModelWithDefault)
        assert isinstance(result.dep, DepService)
        assert result.name == "default"

    def test_resolve_nested_msgspec_models(self, container: Container) -> None:
        """Nested msgspec struct dependency chain resolves correctly."""
        result = container.resolve(NestedMsgspecModel)

        assert isinstance(result, NestedMsgspecModel)
        assert isinstance(result.model, MsgspecModelWithDep)
        assert isinstance(result.model.dep, DepService)

    def test_resolve_regular_class_depending_on_msgspec(self, container: Container) -> None:
        """Regular class depending on msgspec struct resolves correctly."""

        class RegularDependent:
            def __init__(self, model: MsgspecModelWithDep) -> None:
                self.model = model

        result = container.resolve(RegularDependent)

        assert isinstance(result, RegularDependent)
        assert isinstance(result.model, MsgspecModelWithDep)
        assert isinstance(result.model.dep, DepService)
