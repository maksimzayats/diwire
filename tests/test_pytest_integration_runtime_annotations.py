"""Tests for pytest integration with runtime annotations (no __future__)."""

import asyncio
from typing import Annotated, Any, cast

import pytest

from diwire.container import Container
from diwire.integrations.pytest_plugin import (
    _build_async_wrapper,
    _resolve_async,
    pytest_pyfunc_call,
)
from diwire.service_key import ServiceKey
from diwire.types import Injected, Lifetime

pytest_plugins = ["diwire.integrations.pytest_plugin"]


class AsyncService:
    """Service used for async injection."""


@pytest.fixture()
def diwire_container() -> Container:
    container = Container()
    container.register(AsyncService, lifetime=Lifetime.SINGLETON)
    return container


@pytest.mark.asyncio
async def test_async_injection_runtime_annotations(
    service: Annotated[AsyncService, Injected()],
) -> None:
    assert isinstance(service, AsyncService)


async def _async_handler(service: AsyncService) -> AsyncService:
    return service


def test_async_wrapper_resolves_dependencies() -> None:
    container = Container()
    container.register(AsyncService, lifetime=Lifetime.SINGLETON)
    injected = {"service": ServiceKey.from_value(AsyncService)}
    wrapper = _build_async_wrapper(_async_handler, container, None, injected)
    async def _run_wrapper() -> AsyncService:
        return await wrapper()

    result = asyncio.run(_run_wrapper())
    assert isinstance(result, AsyncService)


def test_resolve_async_directly() -> None:
    container = Container()
    container.register(AsyncService, lifetime=Lifetime.SINGLETON)
    injected = {"service": ServiceKey.from_value(AsyncService)}
    resolved = asyncio.run(_resolve_async(container, injected))
    assert isinstance(resolved["service"], AsyncService)


def test_pyfunc_call_async_branch() -> None:
    container = Container()
    container.register(AsyncService, lifetime=Lifetime.SINGLETON)

    async def handler(service: Annotated[AsyncService, Injected()]) -> AsyncService:
        return service

    class DummyItem:
        def __init__(self) -> None:
            self.obj = handler
            self.diwire_container = container
            self.diwire_scope = None

    gen = pytest_pyfunc_call(cast("Any", DummyItem()))
    next(gen)
    next(gen, None)
