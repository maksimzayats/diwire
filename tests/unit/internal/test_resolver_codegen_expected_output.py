from __future__ import annotations

import inspect
import re
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from pathlib import Path

from diwire import BaseScope, Container, FromContext, Injected, Lifetime, Scope
from diwire._internal.providers import ProviderSpec
from diwire._internal.resolvers.templates.renderer import ResolversTemplateRenderer

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


class _SnapshotAsyncInjectWrapperDependency:
    pass


class _SnapshotAsyncInjectWrapperService:
    def __init__(self, dependency: _SnapshotAsyncInjectWrapperDependency) -> None:
        self.dependency = dependency


async def _build_snapshot_async_inject_wrapper_service(
    dependency: Injected[_SnapshotAsyncInjectWrapperDependency],
) -> _SnapshotAsyncInjectWrapperService:
    return _SnapshotAsyncInjectWrapperService(dependency=dependency)


class _SnapshotInlineRootInjectDependency:
    pass


class _SnapshotInlineRootInjectService:
    def __init__(self, dependency: _SnapshotInlineRootInjectDependency) -> None:
        self.dependency = dependency


class _SnapshotInlineRootRequestService:
    def __init__(self, dependency: _SnapshotInlineRootInjectService) -> None:
        self.dependency = dependency


def _build_snapshot_inline_root_inject_service(
    dependency: Injected[_SnapshotInlineRootInjectDependency],
) -> _SnapshotInlineRootInjectService:
    return _SnapshotInlineRootInjectService(dependency=dependency)


def _build_snapshot_inline_root_request_service(
    dependency: _SnapshotInlineRootInjectService,
) -> _SnapshotInlineRootRequestService:
    return _SnapshotInlineRootRequestService(dependency=dependency)


class _SnapshotInjectWrapperVarKwService:
    def __init__(self, options: dict[str, int]) -> None:
        self.options = options


def _build_snapshot_inject_wrapper_varkw_service(
    **options: int,
) -> _SnapshotInjectWrapperVarKwService:
    return _SnapshotInjectWrapperVarKwService(options=options)


class _SnapshotFromContextService:
    def __init__(self, value: int) -> None:
        self.value = value


def _build_snapshot_from_context_service(
    value: FromContext[int],
) -> _SnapshotFromContextService:
    return _SnapshotFromContextService(value=value)


def test_codegen_matches_expected_for_empty_app_root_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_empty.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_scoped_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.add_concrete(
        _SnapshotSession,
        provides=_SnapshotSession,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )
    container.add_concrete(
        _SnapshotRequest,
        provides=_SnapshotRequest,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_scoped.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_async_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.add_factory(
        _provide_int_for_snapshot,
        provides=int,
        lifetime=Lifetime.SCOPED,
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_async.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_sync_generator_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.add_generator(
        _provide_sync_generator_resource,
        provides=_SnapshotGeneratorResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_sync_generator.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_async_context_manager_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.add_context_manager(
        _provide_async_context_resource,
        provides=_SnapshotAsyncContextResource,
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
    container.add_instance(1, provides=positional_type)
    container.add_instance((2, 3), provides=values_type)
    container.add_instance({"first": 1, "second": 2}, provides=options_type)
    container.add_factory(
        _build_snapshot_mixed_shape_service,
        provides=_SnapshotMixedShapeService,
        dependencies={
            positional_type: signature.parameters["positional"],
            values_type: signature.parameters["values"],
            options_type: signature.parameters["options"],
        },
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_mixed_dependency_shapes.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_request_root_filtered_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.add_concrete(
        _SnapshotRequestRootAppService,
        provides=_SnapshotRequestRootAppService,
        scope=Scope.APP,
        lifetime=Lifetime.SCOPED,
    )
    container.add_concrete(
        _SnapshotRequestRootSessionService,
        provides=_SnapshotRequestRootSessionService,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )
    container.add_concrete(
        _SnapshotRequestRootRequestService,
        provides=_SnapshotRequestRootRequestService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    generated = _render(container=container, root_scope=Scope.REQUEST)
    expected = _read_expected("request_root_filtered.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_action_root_filtered_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.add_concrete(
        _SnapshotActionRootRequestService,
        provides=_SnapshotActionRootRequestService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add_concrete(
        _SnapshotActionRootActionService,
        provides=_SnapshotActionRootActionService,
        scope=Scope.ACTION,
        lifetime=Lifetime.SCOPED,
    )
    container.add_concrete(
        _SnapshotActionRootStepService,
        provides=_SnapshotActionRootStepService,
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
    container.add_context_manager(
        _provide_async_context_resource,
        provides=_SnapshotAsyncContextResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add_instance((2, 3), provides=values_type)
    container.add_instance({"first": 1, "second": 2}, provides=options_type)
    container.add_factory(
        _build_snapshot_async_cleanup_signature_service,
        provides=_SnapshotAsyncCleanupSignatureService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
        dependencies={
            _SnapshotAsyncContextResource: signature.parameters["dependency"],
            values_type: signature.parameters["values"],
            options_type: signature.parameters["options"],
        },
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_async_cleanup_signature_mixed.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_inject_wrapper_provider_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.add_instance(
        _SnapshotInjectWrapperDependency(),
        provides=_SnapshotInjectWrapperDependency,
    )

    build_service = container.inject(_build_snapshot_inject_wrapper_service)

    container.add_factory(
        build_service,
        provides=_SnapshotInjectWrapperService,
        lifetime=Lifetime.TRANSIENT,
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_inject_wrapper_provider.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_async_inject_wrapper_provider_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.add_instance(
        _SnapshotAsyncInjectWrapperDependency(),
        provides=_SnapshotAsyncInjectWrapperDependency,
    )

    build_service = container.inject(_build_snapshot_async_inject_wrapper_service)

    container.add_factory(
        build_service,
        provides=_SnapshotAsyncInjectWrapperService,
        lifetime=Lifetime.TRANSIENT,
    )
    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_inject_wrapper_provider_async.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_nested_inline_root_inject_wrapper_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.add_instance(
        _SnapshotInlineRootInjectDependency(),
        provides=_SnapshotInlineRootInjectDependency,
    )

    build_inject_service = container.inject(_build_snapshot_inline_root_inject_service)
    container.add_factory(
        build_inject_service,
        provides=_SnapshotInlineRootInjectService,
        lifetime=Lifetime.TRANSIENT,
    )
    container.add_factory(
        _build_snapshot_inline_root_request_service,
        provides=_SnapshotInlineRootRequestService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_inject_wrapper_nested_inline_root.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_inject_wrapper_varkw_argument_order_graph() -> None:
    signature = inspect.signature(_build_snapshot_inject_wrapper_varkw_service)
    options_type = dict[str, int]

    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.add_instance({"first": 1, "second": 2}, provides=options_type)

    build_service = container.inject(_build_snapshot_inject_wrapper_varkw_service)

    container.add_factory(
        build_service,
        provides=_SnapshotInjectWrapperVarKwService,
        lifetime=Lifetime.TRANSIENT,
        dependencies={
            options_type: signature.parameters["options"],
        },
    )

    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_inject_wrapper_varkw_order.txt")
    assert _normalize_dynamic_metadata(generated) == _normalize_dynamic_metadata(expected)


def test_codegen_matches_expected_for_from_context_dependency_graph() -> None:
    ProviderSpec.SLOT_COUNTER = 0
    container = Container()
    container.add_factory(
        _build_snapshot_from_context_service,
        provides=_SnapshotFromContextService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    generated = _render(container=container, root_scope=Scope.APP)
    expected = _read_expected("app_root_from_context_provider.txt")
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
