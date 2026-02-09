from __future__ import annotations

from diwire.container import Container
from diwire.providers import Lifetime
from diwire.resolvers.templates.planner import LockMode, ResolverGenerationPlanner
from diwire.resolvers.templates.renderer import ResolversTemplateRenderer
from diwire.scope import Scope


class _Config:
    pass


class _Service:
    def __init__(self, config: _Config) -> None:
        self.config = config


class _AsyncService:
    def __init__(self, value: int) -> None:
        self.value = value


async def _provide_int() -> int:
    return 42


async def _provide_async_service(value: int) -> _AsyncService:
    return _AsyncService(value)


def test_renderer_output_is_deterministic_and_composable() -> None:
    container = Container()
    container.register_instance(_Config, instance=_Config())
    container.register_concrete(_Service, concrete_type=_Service, lifetime=Lifetime.TRANSIENT)

    renderer = ResolversTemplateRenderer()
    code_first = renderer.get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )
    code_second = renderer.get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert code_first == code_second
    assert "class RootResolver:" in code_first
    assert "def build_root_resolver(" in code_first
    assert "ResolverProtocol" not in code_first
    assert ") -> RootResolver:" in code_first
    assert "def __enter__(self) -> RootResolver:" in code_first
    assert "async def __aenter__(self) -> RootResolver:" in code_first
    assert (
        "def enter_scope(self, scope: Any | None = None) -> "
        "RootResolver | _SessionResolver | _RequestResolver:"
    ) in code_first
    assert "def enter_scope(self, scope: Any | None = None) -> NoReturn:" in code_first
    assert "def resolve(self, dependency: Any) -> Any:" in code_first
    assert "async def aresolve(self, dependency: Any) -> Any:" in code_first


def test_renderer_output_avoids_reflective_hot_path_tokens() -> None:
    container = Container()
    container.register_instance(_Config, instance=_Config())
    container.register_concrete(_Service, concrete_type=_Service, lifetime=Lifetime.SINGLETON)

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "getattr(" not in code
    assert "__dict__" not in code
    assert "cast(" not in code


def test_planner_selects_async_lock_mode_when_async_specs_exist() -> None:
    container = Container()
    container.register_factory(int, factory=_provide_int, lifetime=Lifetime.SINGLETON)
    container.register_factory(
        _AsyncService,
        factory=_provide_async_service,
        lifetime=Lifetime.SINGLETON,
    )

    plan = ResolverGenerationPlanner(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    ).build()

    assert plan.lock_mode is LockMode.ASYNC
