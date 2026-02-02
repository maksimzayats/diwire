from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from contextvars import Token
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

from diwire.container_context import container_context
from diwire.container_helpers import _build_signature_without_injected

try:
    from fastapi import FastAPI
    from fastapi.routing import APIRoute
except ModuleNotFoundError as exc:  # pragma: no cover - exercised in optional import scenarios
    message = "FastAPI integration requires fastapi. Install with 'fastapi'."
    raise ModuleNotFoundError(message) from exc

if TYPE_CHECKING:
    from diwire.container import Container

_DEFAULT_SCOPE = "request"
_DIWIRE_WRAPPED_ATTR = "__diwire_wrapped__"
_ENDPOINT_ARG_INDEX = 1


def _is_diwire_wrapped(endpoint: Callable[..., Any]) -> bool:
    return bool(getattr(endpoint, _DIWIRE_WRAPPED_ATTR, False))


def _has_injected_params(endpoint: Callable[..., Any]) -> bool:
    try:
        original = inspect.signature(endpoint)
        filtered = _build_signature_without_injected(endpoint)
    except (TypeError, ValueError):
        return False
    return original.parameters != filtered.parameters


def _wrap_endpoint(
    endpoint: Callable[..., Any],
    *,
    scope: str | None,
) -> Callable[..., Any]:
    if _is_diwire_wrapped(endpoint):
        return endpoint
    if not _has_injected_params(endpoint):
        return endpoint
    return cast("Callable[..., Any]", container_context.resolve(endpoint, scope=scope))


def _extract_endpoint(args: Sequence[Any], kwargs: dict[str, Any]) -> Callable[..., Any]:
    endpoint = kwargs.get("endpoint")
    if endpoint is not None:
        return cast("Callable[..., Any]", endpoint)
    if len(args) <= _ENDPOINT_ARG_INDEX:
        message = "FastAPI route initialization missing endpoint argument."
        raise ValueError(message)
    return cast("Callable[..., Any]", args[_ENDPOINT_ARG_INDEX])


def _replace_endpoint(
    args: Sequence[Any],
    kwargs: dict[str, Any],
    endpoint: Callable[..., Any],
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    if "endpoint" in kwargs:
        kwargs["endpoint"] = endpoint
        return tuple(args), kwargs
    if len(args) <= _ENDPOINT_ARG_INDEX:
        message = "FastAPI route initialization missing endpoint argument."
        raise ValueError(message)
    args_list = list(args)
    args_list[_ENDPOINT_ARG_INDEX] = endpoint
    return tuple(args_list), kwargs


@lru_cache(maxsize=16)
def _build_route_class(scope: str | None) -> type[DIWireRoute]:
    class _ConfiguredDIWireRoute(DIWireRoute):
        diwire_scope = scope

    _ConfiguredDIWireRoute.__name__ = f"DIWireRoute_{scope or 'none'}"
    return _ConfiguredDIWireRoute


def _clone_route(route: APIRoute, endpoint: Callable[..., Any]) -> APIRoute:
    route_cls = type(route)
    sig = inspect.signature(route_cls.__init__)
    kwargs: dict[str, Any] = {}
    for name, param in list(sig.parameters.items())[1:]:
        if name == "path":
            kwargs[name] = route.path
            continue
        if name == "endpoint":
            kwargs[name] = endpoint
            continue
        if name == "methods":
            kwargs[name] = route.methods
            continue
        if hasattr(route, name):
            kwargs[name] = getattr(route, name)
            continue
        if name == "dependency_overrides_provider":
            kwargs[name] = getattr(route, "dependency_overrides_provider", None)
            continue
        if param.default is not inspect.Parameter.empty:
            continue
        message = f"Unable to rebuild FastAPI route; missing attribute '{name}'."
        raise RuntimeError(message)
    return route_cls(**kwargs)


def _wrap_existing_routes(routes: list[Any], *, scope: str | None) -> None:
    updated_routes: list[Any] = []
    for route in routes:
        if not isinstance(route, APIRoute):
            updated_routes.append(route)
            continue
        wrapped = _wrap_endpoint(route.endpoint, scope=scope)
        if wrapped is route.endpoint:
            updated_routes.append(route)
            continue
        updated_routes.append(_clone_route(route, wrapped))
    routes[:] = updated_routes


class DIWireRoute(APIRoute):
    """FastAPI route that auto-wraps endpoints with diwire injection."""

    diwire_scope: str | None = _DEFAULT_SCOPE

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        endpoint = _extract_endpoint(args, kwargs)
        wrapped = _wrap_endpoint(endpoint, scope=self.diwire_scope)
        args, kwargs = _replace_endpoint(args, kwargs, wrapped)
        super().__init__(*args, **kwargs)


def setup_diwire(
    app: FastAPI,
    container: Container | None = None,
    *,
    scope: str | None = _DEFAULT_SCOPE,
) -> Token[Container | None] | None:
    """Configure FastAPI to auto-wrap routes for diwire Injected parameters."""
    token: Token[Container | None] | None = None
    if container is not None:
        token = container_context.set_current(container)
        app.state.diwire_container = container
        app.state.diwire_container_token = token

    app.state.diwire_scope = scope
    app.router.route_class = _build_route_class(scope)
    _wrap_existing_routes(app.router.routes, scope=scope)
    return token


__all__ = ["DIWireRoute", "setup_diwire"]
