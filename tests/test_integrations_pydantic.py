"""Tests for Pydantic integration."""

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
