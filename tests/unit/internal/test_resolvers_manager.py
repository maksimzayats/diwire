from __future__ import annotations

from typing import Any, cast

import pytest

from diwire import Scope
from diwire._internal.providers import ProvidersRegistrations
from diwire._internal.resolvers.manager import ResolversManager
from diwire._internal.scope import BaseScope
from diwire.exceptions import DIWireInvalidProviderSpecError


def test_build_root_resolver_rebinds_known_scope_globals_and_skips_missing_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ResolversManager()
    captured_call: dict[str, object] = {}

    def _get_providers_code(
        *,
        root_scope: BaseScope,
        registrations: ProvidersRegistrations,
    ) -> str:
        captured_call["root_scope"] = root_scope
        captured_call["registrations"] = registrations
        return (
            "_scope_obj_1 = 0\n"
            "def build_root_resolver(registrations):\n"
            "    return {\n"
            "        'scope_binding': _scope_obj_1,\n"
            "        'registrations': registrations,\n"
            "    }\n"
        )

    monkeypatch.setattr(manager._template_renderer, "get_providers_code", _get_providers_code)

    registrations = ProvidersRegistrations()
    root_resolver = cast("Any", manager.build_root_resolver(Scope.APP, registrations))

    assert captured_call["root_scope"] is Scope.APP
    assert captured_call["registrations"] is registrations
    assert root_resolver["scope_binding"] is Scope.APP
    assert root_resolver["registrations"] is registrations


def test_build_root_resolver_raises_for_root_scope_without_owner() -> None:
    manager = ResolversManager()

    with pytest.raises(DIWireInvalidProviderSpecError, match="owner"):
        manager.build_root_resolver(BaseScope(1), ProvidersRegistrations())


def test_build_root_resolver_raises_for_invalid_scope_name_before_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ResolversManager()
    called = False

    def _get_providers_code(
        *,
        root_scope: BaseScope,
        registrations: ProvidersRegistrations,
    ) -> str:
        del root_scope, registrations
        nonlocal called
        called = True
        return "def build_root_resolver(registrations):\n    return registrations\n"

    monkeypatch.setattr(manager._template_renderer, "get_providers_code", _get_providers_code)
    monkeypatch.setattr(Scope.APP, "scope_name", "bad.name")

    with pytest.raises(DIWireInvalidProviderSpecError, match="scope_name"):
        manager.build_root_resolver(Scope.APP, ProvidersRegistrations())
    assert called is False


def test_build_root_resolver_raises_for_keyword_scope_name_before_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ResolversManager()
    called = False

    def _get_providers_code(
        *,
        root_scope: BaseScope,
        registrations: ProvidersRegistrations,
    ) -> str:
        del root_scope, registrations
        nonlocal called
        called = True
        return "def build_root_resolver(registrations):\n    return registrations\n"

    monkeypatch.setattr(manager._template_renderer, "get_providers_code", _get_providers_code)
    monkeypatch.setattr(Scope.APP, "scope_name", "for")

    with pytest.raises(DIWireInvalidProviderSpecError, match="keyword"):
        manager.build_root_resolver(Scope.APP, ProvidersRegistrations())
    assert called is False
