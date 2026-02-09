from __future__ import annotations

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


def test_codegen_matches_expected_for_empty_app_root_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_empty.txt")
    assert generated == expected


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
    assert generated == expected


def test_codegen_matches_expected_for_async_graph() -> None:
    async def provide_int() -> int:
        return 42

    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.register_factory(
        int,
        factory=provide_int,
        lifetime=Lifetime.SINGLETON,
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_async.txt")
    assert generated == expected


def _render(*, container: Container, root_scope: BaseScope) -> str:
    renderer = ResolversTemplateRenderer()
    return renderer.get_providers_code(
        root_scope=root_scope,
        registrations=container._providers_registrations,
    )


def _read_expected(file_name: str) -> str:
    return (_EXPECTED_DIR / file_name).read_text()
