from __future__ import annotations

from typing import Any, cast

import pytest

from diwire import Scope
from diwire._internal.providers import ProvidersRegistrations
from diwire._internal.resolvers.manager import ResolversManager
from diwire._internal.scope import BaseScope


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
