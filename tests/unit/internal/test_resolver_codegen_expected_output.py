from __future__ import annotations

import inspect
import re
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from pathlib import Path

from diwire.container import Container
from diwire.markers import Injected
from diwire.providers import Lifetime, ProviderDependency, ProviderSpec
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


class _SnapshotGeneratorResource:
    pass


def _provide_sync_generator_resource() -> Generator[_SnapshotGeneratorResource, None, None]:
    yield _SnapshotGeneratorResource()


class _SnapshotAsyncContextResource:
    pass


@asynccontextmanager
async def _provide_async_context_resource() -> AsyncGenerator[_SnapshotAsyncContextResource, None]:
    yield _SnapshotAsyncContextResource()


class _SnapshotMixedShapeService:
    def __init__(
        self,
        positional: int,
        values: tuple[int, ...],
        options: dict[str, int],
    ) -> None:
        self.positional = positional
        self.values = values
        self.options = options


def _build_snapshot_mixed_shape_service(
    positional: int,
    /,
    *values: int,
    **options: int,
) -> _SnapshotMixedShapeService:
    return _SnapshotMixedShapeService(positional=positional, values=tuple(values), options=options)


class _SnapshotRequestRootAppService:
    pass


class _SnapshotRequestRootSessionService:
    pass


class _SnapshotRequestRootRequestService:
    pass


class _SnapshotActionRootRequestService:
    pass


class _SnapshotActionRootActionService:
    pass


class _SnapshotActionRootStepService:
    pass


class _SnapshotAsyncCleanupSignatureService:
    def __init__(
        self,
        dependency: _SnapshotAsyncContextResource,
        values: tuple[int, ...],
        options: dict[str, int],
    ) -> None:
        self.dependency = dependency
        self.values = values
        self.options = options


def _build_snapshot_async_cleanup_signature_service(
    dependency: _SnapshotAsyncContextResource,
    /,
    *values: int,
    **options: int,
) -> _SnapshotAsyncCleanupSignatureService:
    return _SnapshotAsyncCleanupSignatureService(
        dependency=dependency,
        values=tuple(values),
        options=options,
    )


class _SnapshotInjectWrapperDependency:
    pass


class _SnapshotInjectWrapperService:
    def __init__(self, dependency: _SnapshotInjectWrapperDependency) -> None:
        self.dependency = dependency


def _build_snapshot_inject_wrapper_service(
    dependency: Injected[_SnapshotInjectWrapperDependency],
) -> _SnapshotInjectWrapperService:
    return _SnapshotInjectWrapperService(dependency=dependency)


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


def test_codegen_matches_expected_for_sync_generator_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.register_generator(
        _SnapshotGeneratorResource,
        generator=_provide_sync_generator_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_sync_generator.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_async_context_manager_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.register_context_manager(
        _SnapshotAsyncContextResource,
        context_manager=_provide_async_context_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_async_context_manager.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_mixed_dependency_shape_graph() -> None:
    signature = inspect.signature(_build_snapshot_mixed_shape_service)
    positional_type = int
    values_type = tuple[int, ...]
    options_type = dict[str, int]

    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.register_instance(provides=positional_type, instance=1)
    container.register_instance(provides=values_type, instance=(2, 3))
    container.register_instance(provides=options_type, instance={"first": 1, "second": 2})
    container.register_factory(
        _SnapshotMixedShapeService,
        factory=_build_snapshot_mixed_shape_service,
        dependencies=[
            ProviderDependency(
                provides=positional_type,
                parameter=signature.parameters["positional"],
            ),
            ProviderDependency(
                provides=values_type,
                parameter=signature.parameters["values"],
            ),
            ProviderDependency(
                provides=options_type,
                parameter=signature.parameters["options"],
            ),
        ],
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_mixed_dependency_shapes.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_request_root_filtered_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.register_concrete(
        _SnapshotRequestRootAppService,
        concrete_type=_SnapshotRequestRootAppService,
        scope=Scope.APP,
        lifetime=Lifetime.SINGLETON,
    )
    container.register_concrete(
        _SnapshotRequestRootSessionService,
        concrete_type=_SnapshotRequestRootSessionService,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _SnapshotRequestRootRequestService,
        concrete_type=_SnapshotRequestRootRequestService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    generated = _render(container=container, root_scope=Scope.REQUEST)
    expected = _read_expected("request_root_filtered.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_action_root_filtered_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.register_concrete(
        _SnapshotActionRootRequestService,
        concrete_type=_SnapshotActionRootRequestService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _SnapshotActionRootActionService,
        concrete_type=_SnapshotActionRootActionService,
        scope=Scope.ACTION,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _SnapshotActionRootStepService,
        concrete_type=_SnapshotActionRootStepService,
        scope=Scope.STEP,
        lifetime=Lifetime.SCOPED,
    )
    generated = _render(container=container, root_scope=Scope.ACTION)
    expected = _read_expected("action_root_filtered.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_async_cleanup_mixed_signature_graph() -> None:
    signature = inspect.signature(_build_snapshot_async_cleanup_signature_service)
    values_type = tuple[int, ...]
    options_type = dict[str, int]

    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.register_context_manager(
        _SnapshotAsyncContextResource,
        context_manager=_provide_async_context_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_instance(provides=values_type, instance=(2, 3))
    container.register_instance(provides=options_type, instance={"first": 1, "second": 2})
    container.register_factory(
        _SnapshotAsyncCleanupSignatureService,
        factory=_build_snapshot_async_cleanup_signature_service,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
        dependencies=[
            ProviderDependency(
                provides=_SnapshotAsyncContextResource,
                parameter=signature.parameters["dependency"],
            ),
            ProviderDependency(
                provides=values_type,
                parameter=signature.parameters["values"],
            ),
            ProviderDependency(
                provides=options_type,
                parameter=signature.parameters["options"],
            ),
        ],
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_async_cleanup_signature_mixed.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_inject_wrapper_provider_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.register_instance(
        _SnapshotInjectWrapperDependency,
        instance=_SnapshotInjectWrapperDependency(),
    )

    build_service = container.inject(_build_snapshot_inject_wrapper_service)

    container.register_factory(
        _SnapshotInjectWrapperService,
        factory=build_service,
        lifetime=Lifetime.TRANSIENT,
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_inject_wrapper_provider.txt")
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
