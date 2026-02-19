from __future__ import annotations

import pytest

from diwire import Scope
from diwire._internal.providers import ProvidersRegistrations
from diwire._internal.resolvers.manager import ResolversManager
from diwire._internal.scope import BaseScope
from diwire.exceptions import DIWireInvalidProviderSpecError


def test_build_root_resolver_returns_runtime_resolver_instance() -> None:
    manager = ResolversManager()
    registrations = ProvidersRegistrations()

    root_resolver = manager.build_root_resolver(Scope.APP, registrations)

    assert root_resolver is not None
    assert hasattr(root_resolver, "resolve")
    assert hasattr(root_resolver, "aresolve")


def test_build_root_resolver_raises_for_root_scope_without_owner() -> None:
    manager = ResolversManager()

    with pytest.raises(DIWireInvalidProviderSpecError, match="owner"):
        manager.build_root_resolver(BaseScope(1), ProvidersRegistrations())


def test_build_root_resolver_raises_for_invalid_scope_name_before_compiler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ResolversManager()
    called = False

    def _build_root_resolver(**_kwargs: object) -> object:
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(manager._assembly_compiler, "build_root_resolver", _build_root_resolver)
    monkeypatch.setattr(Scope.APP, "scope_name", "bad.name")

    with pytest.raises(DIWireInvalidProviderSpecError, match="scope_name"):
        manager.build_root_resolver(Scope.APP, ProvidersRegistrations())
    assert called is False


def test_build_root_resolver_raises_for_keyword_scope_name_before_compiler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ResolversManager()
    called = False

    def _build_root_resolver(**_kwargs: object) -> object:
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(manager._assembly_compiler, "build_root_resolver", _build_root_resolver)
    monkeypatch.setattr(Scope.APP, "scope_name", "for")

    with pytest.raises(DIWireInvalidProviderSpecError, match="keyword"):
        manager.build_root_resolver(Scope.APP, ProvidersRegistrations())
    assert called is False
