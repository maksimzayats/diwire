from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from mypy import api as mypy_api

from diwire.container import Container
from diwire.providers import Lifetime, ProviderDependency, ProviderSpec
from diwire.resolvers.templates.renderer import ResolversTemplateRenderer
from diwire.scope import Scope

_PYPROJECT_PATH = Path(__file__).resolve().parents[3] / "pyproject.toml"


class _MypySession:
    pass


class _MypyRequest:
    def __init__(self, session: _MypySession) -> None:
        self.session = session


class _MypyAsyncFactoryService:
    pass


class _MypySyncGeneratorService:
    pass


class _MypyAsyncGeneratorService:
    pass


class _MypySyncContextManagerService:
    pass


class _MypyAsyncContextManagerService:
    pass


class _MypyMixedShapeService:
    def __init__(
        self,
        positional: int,
        values: tuple[int, ...],
        options: dict[str, int],
    ) -> None:
        self.positional = positional
        self.values = values
        self.options = options


class _MypyAsyncDependencyConsumer:
    def __init__(self, dependency: _MypyAsyncGeneratorService) -> None:
        self.dependency = dependency


class _MypyRequestRootAppService:
    pass


class _MypyRequestRootRequestService:
    pass


async def _provide_async_factory_service() -> _MypyAsyncFactoryService:
    return _MypyAsyncFactoryService()


def _provide_sync_generator_service() -> Generator[_MypySyncGeneratorService, None, None]:
    yield _MypySyncGeneratorService()


async def _provide_async_generator_service() -> AsyncGenerator[_MypyAsyncGeneratorService, None]:
    yield _MypyAsyncGeneratorService()


@contextmanager
def _provide_sync_context_manager_service() -> Generator[
    _MypySyncContextManagerService,
    None,
    None,
]:
    yield _MypySyncContextManagerService()


@asynccontextmanager
async def _provide_async_context_manager_service() -> AsyncGenerator[
    _MypyAsyncContextManagerService,
    None,
]:
    yield _MypyAsyncContextManagerService()


def _provide_mixed_shape_service(
    positional: int,
    /,
    *values: int,
    **options: int,
) -> _MypyMixedShapeService:
    return _MypyMixedShapeService(positional=positional, values=tuple(values), options=options)


def _provide_async_dependency_consumer(
    dependency: _MypyAsyncGeneratorService,
) -> _MypyAsyncDependencyConsumer:
    return _MypyAsyncDependencyConsumer(dependency)


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

        # Validate generation+write cycle stability for the same scenario artifact.
        generated_module_path.write_text(code)
        stdout, stderr, exit_status = mypy_api.run(
            [
                "--config-file",
                str(_PYPROJECT_PATH),
                str(generated_module_path),
            ],
        )
        assert exit_status == 0, (
            f"Mypy failed after rewrite for {scenario} generated module."
            f"\nstdout:\n{stdout}\nstderr:\n{stderr}"
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

    async_factory_container = Container()
    async_factory_container.register_factory(
        _MypyAsyncFactoryService,
        factory=_provide_async_factory_service,
        lifetime=Lifetime.SINGLETON,
    )

    sync_generator_container = Container()
    sync_generator_container.register_generator(
        _MypySyncGeneratorService,
        generator=_provide_sync_generator_service,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    async_generator_container = Container()
    async_generator_container.register_generator(
        _MypyAsyncGeneratorService,
        generator=_provide_async_generator_service,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    sync_context_manager_container = Container()
    sync_context_manager_container.register_context_manager(
        _MypySyncContextManagerService,
        context_manager=_provide_sync_context_manager_service,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    async_context_manager_container = Container()
    async_context_manager_container.register_context_manager(
        _MypyAsyncContextManagerService,
        context_manager=_provide_async_context_manager_service,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    mixed_dependency_shapes_container = Container()
    mixed_signature = inspect.signature(_provide_mixed_shape_service)
    positional_type = int
    values_type = tuple[int, ...]
    options_type = dict[str, int]
    mixed_dependency_shapes_container.register_instance(provides=positional_type, instance=1)
    mixed_dependency_shapes_container.register_instance(provides=values_type, instance=(2, 3))
    mixed_dependency_shapes_container.register_instance(
        provides=options_type,
        instance={"first": 1, "second": 2},
    )
    mixed_dependency_shapes_container.register_factory(
        _MypyMixedShapeService,
        factory=_provide_mixed_shape_service,
        dependencies=[
            ProviderDependency(
                provides=positional_type,
                parameter=mixed_signature.parameters["positional"],
            ),
            ProviderDependency(
                provides=values_type,
                parameter=mixed_signature.parameters["values"],
            ),
            ProviderDependency(
                provides=options_type,
                parameter=mixed_signature.parameters["options"],
            ),
        ],
    )

    async_dependency_propagation_container = Container()
    async_dependency_propagation_container.register_generator(
        _MypyAsyncGeneratorService,
        generator=_provide_async_generator_service,
        lifetime=Lifetime.SINGLETON,
    )
    async_dependency_propagation_container.register_factory(
        _MypyAsyncDependencyConsumer,
        factory=_provide_async_dependency_consumer,
        lifetime=Lifetime.SINGLETON,
    )

    mixed_async_cleanup_container = Container()
    mixed_async_cleanup_container.register_generator(
        _MypyAsyncGeneratorService,
        generator=_provide_async_generator_service,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    mixed_async_cleanup_container.register_context_manager(
        _MypySyncContextManagerService,
        context_manager=_provide_sync_context_manager_service,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    mixed_async_cleanup_container.register_factory(
        _MypyAsyncDependencyConsumer,
        factory=_provide_async_dependency_consumer,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    request_root_container = Container()
    request_root_container.register_concrete(
        _MypyRequestRootAppService,
        concrete_type=_MypyRequestRootAppService,
        scope=Scope.APP,
        lifetime=Lifetime.SINGLETON,
    )
    request_root_container.register_concrete(
        _MypySession,
        concrete_type=_MypySession,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )
    request_root_container.register_concrete(
        _MypyRequestRootRequestService,
        concrete_type=_MypyRequestRootRequestService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
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
        "async_factory": renderer.get_providers_code(
            root_scope=Scope.APP,
            registrations=async_factory_container._providers_registrations,
        ),
        "sync_generator": renderer.get_providers_code(
            root_scope=Scope.APP,
            registrations=sync_generator_container._providers_registrations,
        ),
        "async_generator": renderer.get_providers_code(
            root_scope=Scope.APP,
            registrations=async_generator_container._providers_registrations,
        ),
        "sync_context_manager": renderer.get_providers_code(
            root_scope=Scope.APP,
            registrations=sync_context_manager_container._providers_registrations,
        ),
        "async_context_manager": renderer.get_providers_code(
            root_scope=Scope.APP,
            registrations=async_context_manager_container._providers_registrations,
        ),
        "mixed_dependency_shapes": renderer.get_providers_code(
            root_scope=Scope.APP,
            registrations=mixed_dependency_shapes_container._providers_registrations,
        ),
        "async_dependency_propagation": renderer.get_providers_code(
            root_scope=Scope.APP,
            registrations=async_dependency_propagation_container._providers_registrations,
        ),
        "mixed_async_cleanup": renderer.get_providers_code(
            root_scope=Scope.APP,
            registrations=mixed_async_cleanup_container._providers_registrations,
        ),
        "request_root_filtered": renderer.get_providers_code(
            root_scope=Scope.REQUEST,
            registrations=request_root_container._providers_registrations,
        ),
    }
