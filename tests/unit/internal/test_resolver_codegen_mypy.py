from __future__ import annotations

from pathlib import Path

from mypy import api as mypy_api

from diwire.container import Container
from diwire.providers import Lifetime, ProviderSpec
from diwire.resolvers.templates.renderer import ResolversTemplateRenderer
from diwire.scope import Scope

_PYPROJECT_PATH = Path(__file__).resolve().parents[3] / "pyproject.toml"


class _MypySession:
    pass


class _MypyRequest:
    def __init__(self, session: _MypySession) -> None:
        self.session = session


class _MypyAsyncService:
    pass


async def _provide_async_service() -> _MypyAsyncService:
    return _MypyAsyncService()


def test_generated_code_passes_mypy_with_method_replacement_ignored(tmp_path: Path) -> None:
    slot_counter = ProviderSpec.SLOT_COUNTER
    try:
        ProviderSpec.SLOT_COUNTER = 0
        generated_modules = _render_generated_modules()
    finally:
        ProviderSpec.SLOT_COUNTER = slot_counter

    for scenario, code in generated_modules.items():
        generated_module_path = tmp_path / f"{scenario}_generated.py"
        generated_module_path.write_text(code)

        stdout, stderr, exit_status = mypy_api.run(
            [
                "--config-file",
                str(_PYPROJECT_PATH),
                str(generated_module_path),
            ],
        )

        assert exit_status == 0, (
            f"Mypy failed for {scenario} generated module.\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )


def _render_generated_modules() -> dict[str, str]:
    renderer = ResolversTemplateRenderer()

    empty_container = Container()

    scoped_container = Container()
    scoped_container.register_concrete(
        _MypySession,
        concrete_type=_MypySession,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )
    scoped_container.register_concrete(
        _MypyRequest,
        concrete_type=_MypyRequest,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    async_container = Container()
    async_container.register_factory(
        _MypyAsyncService,
        factory=_provide_async_service,
        lifetime=Lifetime.SINGLETON,
    )

    return {
        "empty": renderer.get_providers_code(
            root_scope=Scope.APP,
            registrations=empty_container._providers_registrations,
        ),
        "scoped": renderer.get_providers_code(
            root_scope=Scope.APP,
            registrations=scoped_container._providers_registrations,
        ),
        "async": renderer.get_providers_code(
            root_scope=Scope.APP,
            registrations=async_container._providers_registrations,
        ),
    }
