from __future__ import annotations

import asyncio
import importlib
import inspect
from collections.abc import Awaitable, Callable, Iterator
from functools import lru_cache, wraps
from typing import TYPE_CHECKING, Annotated, Any, cast, get_args, get_origin

import pytest

if TYPE_CHECKING:
    from diwire.container import Container
    from diwire.dependencies import DependenciesExtractor
    from diwire.service_key import ServiceKey

_DEFAULT_SCOPE = "test_function"
_INVALID_SCOPE_MARKER_MESSAGE = "diwire_scope marker expects a string or None"


class DIWireInvalidScopeMarkerError(Exception):
    """Invalid scope marker specified for pytest integration."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


@lru_cache(maxsize=1)
def _get_dependencies_extractor() -> DependenciesExtractor:
    module = importlib.import_module("diwire.dependencies")
    return module.DependenciesExtractor()


@lru_cache(maxsize=1)
def _get_container_cls() -> type[Container]:
    module = importlib.import_module("diwire.container")
    return module.Container


@lru_cache(maxsize=1)
def _get_injected_marker_cls() -> type[Any]:
    module = importlib.import_module("diwire.types")
    return module.Injected


@lru_cache(maxsize=1)
def _get_service_key_cls() -> type[ServiceKey]:
    module = importlib.import_module("diwire.service_key")
    return module.ServiceKey


def _has_injected_annotation(param: inspect.Parameter) -> bool:
    annotation = param.annotation
    if annotation is inspect.Parameter.empty:
        return False
    if isinstance(annotation, str):
        return "Injected" in annotation
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        injected_marker = _get_injected_marker_cls()
        return any(isinstance(arg, injected_marker) for arg in args[1:])
    return False


def _build_signature_without_injected(func: Any) -> inspect.Signature:
    original_sig = inspect.signature(func)
    new_params = [p for p in original_sig.parameters.values() if not _has_injected_annotation(p)]
    return original_sig.replace(parameters=new_params)


def _normalize_scope(scope: str | None) -> str | None:
    if scope is None:
        return None
    normalized = scope.strip()
    return normalized or None


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("diwire")
    group.addoption(
        "--diwire-scope",
        action="store",
        dest="diwire_scope",
        default=None,
        help="Container scope name used for Injected parameters.",
    )
    parser.addini(
        "diwire_scope",
        "Container scope name used for Injected parameters.",
        default=_DEFAULT_SCOPE,
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "diwire_scope(scope): override diwire injection scope for a test",
    )


@pytest.fixture()
def diwire_container() -> Container:
    return _get_container_cls()()


def _resolve_scope_from_config(pytestconfig: pytest.Config) -> str | None:
    scope = cast("str | None", pytestconfig.getoption("diwire_scope"))
    if scope is None:
        scope = cast("str | None", pytestconfig.getini("diwire_scope"))
    return _normalize_scope(scope)


def _resolve_scope_override(pyfuncitem: pytest.Function) -> tuple[bool, str | None]:
    marker = pyfuncitem.get_closest_marker("diwire_scope")
    if marker is None:
        return False, None
    raw_scope = marker.args[0] if marker.args else marker.kwargs.get("scope")
    if raw_scope is None:
        return True, None
    if isinstance(raw_scope, str):
        return True, _normalize_scope(raw_scope)
    raise DIWireInvalidScopeMarkerError(_INVALID_SCOPE_MARKER_MESSAGE)


@pytest.fixture()
def diwire_scope(pytestconfig: pytest.Config) -> str | None:
    return _resolve_scope_from_config(pytestconfig)


@pytest.fixture(autouse=True)
def _diwire_state(
    request: pytest.FixtureRequest,
    diwire_container: Container,
    diwire_scope: str | None,
) -> None:
    node = cast("Any", request.node)
    node.diwire_container = diwire_container
    node.diwire_scope = diwire_scope


def pytest_pycollect_makeitem(
    collector: Any,
    name: str,
    obj: object,
) -> Any | None:
    if not callable(obj):
        return None
    if not collector.istestfunction(obj, name):
        return None
    original_sig = inspect.signature(obj)
    filtered_sig = _build_signature_without_injected(obj)
    if filtered_sig.parameters != original_sig.parameters:
        cast("Any", obj).__signature__ = filtered_sig
    return None


def _resolve_sync(container: Container, injected: dict[str, ServiceKey]) -> dict[str, Any]:
    return {name: container.resolve(dep) for name, dep in injected.items()}


async def _resolve_async(container: Container, injected: dict[str, ServiceKey]) -> dict[str, Any]:
    coros = {name: container.aresolve(dep) for name, dep in injected.items()}
    tasks = [asyncio.create_task(coro) for coro in coros.values()]
    results = await asyncio.gather(*tasks)
    return dict(zip(coros.keys(), results, strict=True))


def _build_async_wrapper(
    original: Callable[..., Awaitable[Any]],
    container: Container,
    scope_name: str | None,
    injected_deps: dict[str, ServiceKey],
) -> Callable[..., Awaitable[Any]]:
    @wraps(original)
    async def wrapped(**kwargs: Any) -> Any:
        if scope_name is None:
            resolved = await _resolve_async(container, injected_deps)
            for name, value in resolved.items():
                kwargs.setdefault(name, value)
            return await original(**kwargs)
        async with container.enter_scope(scope_name):
            resolved = await _resolve_async(container, injected_deps)
            for name, value in resolved.items():
                kwargs.setdefault(name, value)
            return await original(**kwargs)

    return wrapped


def _build_sync_wrapper(
    original: Callable[..., Any],
    container: Container,
    scope_name: str | None,
    injected_deps: dict[str, ServiceKey],
) -> Callable[..., Any]:
    @wraps(original)
    def wrapped(**kwargs: Any) -> Any:
        if scope_name is None:
            resolved = _resolve_sync(container, injected_deps)
            for name, value in resolved.items():
                kwargs.setdefault(name, value)
            return original(**kwargs)
        with container.enter_scope(scope_name):
            resolved = _resolve_sync(container, injected_deps)
            for name, value in resolved.items():
                kwargs.setdefault(name, value)
            return original(**kwargs)

    return wrapped


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> Iterator[None]:
    injected_deps = _get_dependencies_extractor().get_injected_dependencies(
        service_key=_get_service_key_cls().from_value(pyfuncitem.obj),
    )
    if not injected_deps:
        yield
        return

    item = cast("Any", pyfuncitem)
    container = cast("Container", item.diwire_container)
    scope_name = cast("str | None", item.diwire_scope)
    has_override, marker_scope = _resolve_scope_override(pyfuncitem)
    if has_override:
        scope_name = marker_scope
    original = pyfuncitem.obj
    is_async = inspect.iscoroutinefunction(original)

    if is_async:
        wrapped = _build_async_wrapper(original, container, scope_name, injected_deps)
    else:
        wrapped = _build_sync_wrapper(original, container, scope_name, injected_deps)
    pyfuncitem.obj = wrapped
    try:
        yield
    finally:
        pyfuncitem.obj = original
