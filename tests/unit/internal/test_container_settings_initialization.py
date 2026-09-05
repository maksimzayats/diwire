from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[3]


def _run_fresh_process(program: str, *, site_enabled: bool = True) -> None:
    command = [sys.executable]
    if not site_enabled:
        command.append("-S")
    command.extend(["-c", textwrap.dedent(program)])
    environment = {
        **os.environ,
        "PYTHONPATH": str(_ROOT / "src"),
        "DIWIRE_LAZY_SETTINGS_VALUE": "73",
    }
    # Run the current interpreter with an explicit program, without a shell.
    result = subprocess.run(  # noqa: S603
        command,
        cwd=_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("site_enabled", [True, False])
def test_explicit_registration_does_not_import_optional_settings(*, site_enabled: bool) -> None:
    _run_fresh_process(
        """
        import importlib.abc
        import sys

        class RejectOptionalImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] in {"pydantic", "pydantic_settings", "pydantic_core"}:
                    raise AssertionError(f"Unexpected optional import: {fullname}")
                return None

        sys.meta_path.insert(0, RejectOptionalImports())
        from diwire import Container, DependencyRegistrationPolicy, MissingPolicy

        class Service:
            pass

        container = Container(
            missing_policy=MissingPolicy.ERROR,
            dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
            use_resolver_context=False,
        )
        try:
            container.add(Service)
            assert isinstance(container.resolve(Service), Service)
        finally:
            container.close()
        assert "diwire._internal.integrations.pydantic_settings" not in sys.modules
        assert not any(
            name.split(".")[0] in {"pydantic", "pydantic_settings", "pydantic_core"}
            for name in sys.modules
        )
        """,
        site_enabled=site_enabled,
    )


def test_plain_autoregistration_initializes_without_optional_dependencies() -> None:
    _run_fresh_process(
        """
        import sys
        from diwire import Container

        assert "diwire._internal.integrations.pydantic_settings" not in sys.modules

        class Service:
            pass

        container = Container(use_resolver_context=False)
        try:
            first = container.resolve(Service)
            assert isinstance(first, Service)
            assert container.resolve(Service) is first
        finally:
            container.close()

        assert "diwire._internal.integrations.pydantic_settings" in sys.modules
        from diwire._internal.integrations import pydantic_settings
        assert pydantic_settings.SETTINGS_BASES == ()
        assert pydantic_settings.is_pydantic_settings_subclass(Service) is False
        assert pydantic_settings.is_pydantic_settings_subclass(object()) is False
        assert not any(
            name.split(".")[0] in {"pydantic", "pydantic_settings", "pydantic_core"}
            for name in sys.modules
        )
        """,
        site_enabled=False,
    )


@pytest.mark.parametrize("settings_first", [True, False])
def test_first_settings_autoregistration_preserves_root_factory(*, settings_first: bool) -> None:
    if importlib.util.find_spec("pydantic_settings") is None:
        pytest.skip("pydantic_settings is unavailable")
    imports = (
        "from pydantic_settings import BaseSettings, SettingsConfigDict\n"
        "from diwire import Container, Lifetime, Scope\n"
        if settings_first
        else "from diwire import Container, Lifetime, Scope\n"
        "from pydantic_settings import BaseSettings, SettingsConfigDict\n"
    )
    _run_fresh_process(
        imports
        + textwrap.dedent(
            """
            import sys

            class Settings(BaseSettings):
                model_config = SettingsConfigDict(env_prefix="DIWIRE_LAZY_SETTINGS_")
                value: int = 12

            assert "diwire._internal.integrations.pydantic_settings" not in sys.modules
            container = Container(use_resolver_context=False)
            try:
                first = container.resolve(Settings)
                assert first.value == 73
                assert container.resolve(Settings) is first
                registration = container._providers_registrations.get_by_type(Settings)
                assert registration.factory is not None
                assert registration.concrete_type is None
                assert registration.scope is Scope.APP
                assert registration.lifetime is Lifetime.SCOPED
                with container.enter_scope(Scope.REQUEST) as request:
                    assert request.resolve(Settings) is first
            finally:
                container.close()
            """
        ),
    )


def test_concurrent_first_settings_use_initializes_complete_integration() -> None:
    if importlib.util.find_spec("pydantic_settings") is None:
        pytest.skip("pydantic_settings is unavailable")
    _run_fresh_process(
        """
        import sys
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from pydantic_settings import BaseSettings, SettingsConfigDict
        from diwire import Container, Lifetime, ResolverContext, Scope

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(env_prefix="DIWIRE_LAZY_SETTINGS_")
            value: int = 12

        assert "diwire._internal.integrations.pydantic_settings" not in sys.modules
        barrier = threading.Barrier(4, timeout=10)

        def resolve_settings():
            container = Container(resolver_context=ResolverContext(), use_resolver_context=False)
            try:
                barrier.wait()
                first = container.resolve(Settings)
                assert first.value == 73
                assert container.resolve(Settings) is first
                registration = container._providers_registrations.get_by_type(Settings)
                assert registration.factory is not None
                assert registration.concrete_type is None
                assert registration.scope is Scope.APP
                assert registration.lifetime is Lifetime.SCOPED
                return first
            finally:
                container.close()

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(resolve_settings) for _ in range(4)]
            results = [future.result(timeout=15) for future in futures]
        assert len({id(result) for result in results}) == 4
        from diwire._internal.integrations import pydantic_settings
        assert BaseSettings in pydantic_settings.SETTINGS_BASES
        assert pydantic_settings.is_pydantic_settings_subclass(Settings) is True
        """,
    )


def test_settings_detection_monkeypatch_does_not_load_integration() -> None:
    _run_fresh_process(
        """
        import sys
        import diwire._internal.container as container_module
        from diwire import Container, Lifetime, Scope

        class SettingsLike:
            pass

        container_module.is_pydantic_settings_subclass = lambda value: value is SettingsLike
        container = Container(use_resolver_context=False)
        try:
            first = container.resolve(SettingsLike)
            assert isinstance(first, SettingsLike)
            assert container.resolve(SettingsLike) is first
            registration = container._providers_registrations.get_by_type(SettingsLike)
            assert registration.factory is not None
            assert registration.concrete_type is None
            assert registration.scope is Scope.APP
            assert registration.lifetime is Lifetime.SCOPED
        finally:
            container.close()
        assert "diwire._internal.integrations.pydantic_settings" not in sys.modules
        """,
        site_enabled=False,
    )


def test_optional_integration_failure_propagates_at_first_use_and_can_retry() -> None:
    _run_fresh_process(
        """
        import importlib.abc
        import sys

        failure = RuntimeError("settings import sentinel")

        class RejectIntegration(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "diwire._internal.integrations.pydantic_settings":
                    raise failure
                return None

        blocker = RejectIntegration()
        sys.meta_path.insert(0, blocker)
        from diwire import Container, DependencyRegistrationPolicy, MissingPolicy

        class Service:
            pass

        explicit = Container(
            missing_policy=MissingPolicy.ERROR,
            dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
            use_resolver_context=False,
        )
        try:
            explicit.add(Service)
            assert isinstance(explicit.resolve(Service), Service)
        finally:
            explicit.close()

        automatic = Container(use_resolver_context=False)
        try:
            try:
                automatic.resolve(Service)
            except RuntimeError as error:
                assert error is failure
            else:
                raise AssertionError("Integration failure was swallowed")
            assert automatic._providers_registrations.find_by_type(Service) is None
            assert "diwire._internal.integrations.pydantic_settings" not in sys.modules
            sys.meta_path.remove(blocker)
            first = automatic.resolve(Service)
            assert isinstance(first, Service)
            assert automatic.resolve(Service) is first
        finally:
            automatic.close()
        """,
        site_enabled=False,
    )
