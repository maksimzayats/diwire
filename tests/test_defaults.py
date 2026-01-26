"""Tests for defaults module."""

from diwire.defaults import (
    DEFAULT_AUTOREGISTER_IGNORES,
    DEFAULT_AUTOREGISTER_LIFETIME,
    DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES,
)
from diwire.integrations.pydantic import BaseSettings
from diwire.registry import Registration
from diwire.types import Lifetime


class TestDefaultAutoregisterIgnores:
    def test_builtin_types_in_ignore_list(self) -> None:
        """Builtin types are in ignore list."""
        assert int in DEFAULT_AUTOREGISTER_IGNORES
        assert str in DEFAULT_AUTOREGISTER_IGNORES
        assert float in DEFAULT_AUTOREGISTER_IGNORES
        assert bool in DEFAULT_AUTOREGISTER_IGNORES
        assert list in DEFAULT_AUTOREGISTER_IGNORES
        assert dict in DEFAULT_AUTOREGISTER_IGNORES
        assert set in DEFAULT_AUTOREGISTER_IGNORES
        assert tuple in DEFAULT_AUTOREGISTER_IGNORES

    def test_ignore_list_is_set(self) -> None:
        """Ignore list is a set."""
        assert isinstance(DEFAULT_AUTOREGISTER_IGNORES, set)

    def test_all_expected_builtins_present(self) -> None:
        """All expected builtins are present."""
        expected = {int, str, float, bool, list, dict, set, tuple}
        assert expected <= DEFAULT_AUTOREGISTER_IGNORES


class TestDefaultAutoregisterRegistrationFactories:
    def test_base_settings_factory_exists(self) -> None:
        """BaseSettings has a factory."""
        assert BaseSettings in DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES

    def test_base_settings_factory_returns_registration(self) -> None:
        """BaseSettings factory returns Registration."""

        class MySettings(BaseSettings):  # type: ignore[misc]
            pass

        factory = DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES[BaseSettings]
        registration = factory(MySettings)  # type: ignore[no-untyped-call]

        assert isinstance(registration, Registration)

    def test_base_settings_factory_creates_singleton(self) -> None:
        """BaseSettings registration has lifetime singleton."""

        class MySettings(BaseSettings):  # type: ignore[misc]
            pass

        factory = DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES[BaseSettings]
        registration = factory(MySettings)  # type: ignore[no-untyped-call]

        assert registration.lifetime == Lifetime.SINGLETON


class TestDefaultAutoregisterLifetime:
    def test_default_kind_is_transient(self) -> None:
        """Default lifetime is TRANSIENT."""
        assert DEFAULT_AUTOREGISTER_LIFETIME == Lifetime.TRANSIENT
