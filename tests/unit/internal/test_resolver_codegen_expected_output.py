from __future__ import annotations

import re
from pathlib import Path

from diwire.container import Container
from diwire.providers import Lifetime, ProviderSpec
from diwire.resolvers.templates.renderer import ResolversTemplateRenderer
from diwire.scope import BaseScope, Scope

_EXPECTED_DIR = Path(__file__).with_name("codegen_expected")


class _SnapshotSession:
    pass


class _SnapshotRequest:
    def __init__(self, session: _SnapshotSession) -> None:
        self.session = session


async def _provide_int_for_snapshot() -> int:
    return 42


def test_codegen_matches_expected_for_empty_app_root_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_empty.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_scoped_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.register_concrete(
        _SnapshotSession,
        concrete_type=_SnapshotSession,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _SnapshotRequest,
        concrete_type=_SnapshotRequest,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_scoped.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_async_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.register_factory(
        int,
        factory=_provide_int_for_snapshot,
        lifetime=Lifetime.SINGLETON,
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_async.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def _render(*, container: Container, root_scope: BaseScope) -> str:
    renderer = ResolversTemplateRenderer()
    return renderer.get_providers_code(
        root_scope=root_scope,
        registrations=container._providers_registrations,
    )


def _read_expected(file_name: str) -> str:
    return (_EXPECTED_DIR / file_name).read_text()


def _normalize_dynamic_metadata(code: str) -> str:
    return re.sub(
        r"diwire version used for generation: .*",
        "diwire version used for generation: <dynamic>",
        code,
    )
