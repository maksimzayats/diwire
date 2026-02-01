"""Tests for Pydantic integration."""

import pydantic.dataclasses as pdc
from pydantic import BaseModel

from diwire.container import Container
from diwire.defaults import DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES
from diwire.integrations.pydantic import BaseSettings
from diwire.types import Lifetime


class TestBaseSettingsImport:
    def test_base_settings_import_with_pydantic_installed(self) -> None:
        """BaseSettings is importable."""
        assert BaseSettings is not None

    def test_base_settings_fallback_without_pydantic(self) -> None:
        """When pydantic_settings not installed, fallback class exists."""
        # It should be a class
        assert isinstance(BaseSettings, type)


class TestBaseSettingsAutoRegistration:
    def test_auto_registration_of_base_settings_subclass(
        self,
        container: Container,
    ) -> None:
        """BaseSettings subclass is auto-registered."""

        class MySettings(BaseSettings):  # type: ignore[misc]
            pass

        instance = container.resolve(MySettings)

        assert isinstance(instance, MySettings)

    def test_base_settings_creates_singleton(self, container: Container) -> None:
        """BaseSettings creates singleton."""

        class MySingletonSettings(BaseSettings):  # type: ignore[misc]
            pass

        instance1 = container.resolve(MySingletonSettings)
        instance2 = container.resolve(MySingletonSettings)

        assert instance1 is instance2

    def test_base_settings_uses_factory(self, container: Container) -> None:
        """BaseSettings registration uses factory."""
        assert BaseSettings in DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES

        factory_func = DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES[BaseSettings]

        class TestSettings(BaseSettings):  # type: ignore[misc]
            pass

        registration = factory_func(TestSettings)  # type: ignore[no-untyped-call]

        assert registration.lifetime == Lifetime.SINGLETON
        assert registration.factory is not None


class DepService:
    pass


class PydanticModelWithDep(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    dep: DepService


class NestedPydanticModel(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    model: PydanticModelWithDep


class PydanticModelWithDefault(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    dep: DepService
    name: str = "default"


class EmptyPydanticModel(BaseModel):
    pass


class TestPydanticBaseModelResolution:
    def test_resolve_pydantic_model_with_dependency(self, container: Container) -> None:
        """Pydantic model with a dependency field resolves correctly."""
        result = container.resolve(PydanticModelWithDep)

        assert isinstance(result, PydanticModelWithDep)
        assert isinstance(result.dep, DepService)

    def test_resolve_empty_pydantic_model(self, container: Container) -> None:
        """Pydantic model with no fields resolves correctly."""
        result = container.resolve(EmptyPydanticModel)

        assert isinstance(result, EmptyPydanticModel)

    def test_resolve_pydantic_model_with_default(self, container: Container) -> None:
        """Pydantic model with default values resolves correctly."""
        result = container.resolve(PydanticModelWithDefault)

        assert isinstance(result, PydanticModelWithDefault)
        assert isinstance(result.dep, DepService)
        assert result.name == "default"

    def test_resolve_nested_pydantic_models(self, container: Container) -> None:
        """Nested pydantic model dependency chain resolves correctly."""
        result = container.resolve(NestedPydanticModel)

        assert isinstance(result, NestedPydanticModel)
        assert isinstance(result.model, PydanticModelWithDep)
        assert isinstance(result.model.dep, DepService)

    def test_resolve_regular_class_depending_on_pydantic(self, container: Container) -> None:
        """Regular class depending on pydantic model resolves correctly."""

        class RegularDependent:
            def __init__(self, model: PydanticModelWithDep) -> None:
                self.model = model

        result = container.resolve(RegularDependent)

        assert isinstance(result, RegularDependent)
        assert isinstance(result.model, PydanticModelWithDep)
        assert isinstance(result.model.dep, DepService)


@pdc.dataclass(config={"arbitrary_types_allowed": True})
class PydanticDCWithDep:
    dep: DepService


@pdc.dataclass(config={"arbitrary_types_allowed": True})
class NestedPydanticDC:
    model: PydanticDCWithDep


@pdc.dataclass(config={"arbitrary_types_allowed": True})
class PydanticDCWithDefault:
    dep: DepService
    name: str = "default"


@pdc.dataclass
class EmptyPydanticDC:
    pass


class TestPydanticDataclassResolution:
    def test_resolve_pydantic_dataclass_with_dependency(self, container: Container) -> None:
        """Pydantic dataclass with a dependency field resolves correctly."""
        result = container.resolve(PydanticDCWithDep)

        assert isinstance(result, PydanticDCWithDep)
        assert isinstance(result.dep, DepService)

    def test_resolve_empty_pydantic_dataclass(self, container: Container) -> None:
        """Pydantic dataclass with no fields resolves correctly."""
        result = container.resolve(EmptyPydanticDC)

        assert isinstance(result, EmptyPydanticDC)

    def test_resolve_pydantic_dataclass_with_default(self, container: Container) -> None:
        """Pydantic dataclass with default values resolves correctly."""
        result = container.resolve(PydanticDCWithDefault)

        assert isinstance(result, PydanticDCWithDefault)
        assert isinstance(result.dep, DepService)
        assert result.name == "default"

    def test_resolve_nested_pydantic_dataclasses(self, container: Container) -> None:
        """Nested pydantic dataclass dependency chain resolves correctly."""
        result = container.resolve(NestedPydanticDC)

        assert isinstance(result, NestedPydanticDC)
        assert isinstance(result.model, PydanticDCWithDep)
        assert isinstance(result.model.dep, DepService)

    def test_resolve_regular_class_depending_on_pydantic_dataclass(
        self,
        container: Container,
    ) -> None:
        """Regular class depending on pydantic dataclass resolves correctly."""

        class RegularDependent:
            def __init__(self, model: PydanticDCWithDep) -> None:
                self.model = model

        result = container.resolve(RegularDependent)

        assert isinstance(result, RegularDependent)
        assert isinstance(result.model, PydanticDCWithDep)
        assert isinstance(result.model.dep, DepService)
