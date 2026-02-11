from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, cast

from diwire import Container, Injected
from diwire.integrations.pytest_plugin import pytest_pycollect_makeitem, pytest_pyfunc_call


class _Service:
    def __init__(self, value: str = "service") -> None:
        self.value = value


class _DummyCollector:
    def __init__(self, *, is_test_function: bool) -> None:
        self._is_test_function = is_test_function

    def istestfunction(self, obj: object, name: str) -> bool:
        _ = obj, name
        return self._is_test_function


class _DummyPyFuncItem:
    def __init__(self, *, obj: Callable[..., Any], container: Container | None) -> None:
        self.obj = obj
        if container is not None:
            self._diwire_container = container


def test_pycollect_makeitem_ignores_non_callable_objects() -> None:
    collector = _DummyCollector(is_test_function=True)

    result = pytest_pycollect_makeitem(collector=collector, name="test_value", obj=1)

    assert result is None


def test_pycollect_makeitem_ignores_non_test_callables() -> None:
    collector = _DummyCollector(is_test_function=False)

    def helper(value: int, service: Injected[_Service]) -> None:
        _ = value, service

    original_signature = inspect.signature(helper)
    result = pytest_pycollect_makeitem(collector=collector, name="helper", obj=helper)

    assert result is None
    assert inspect.signature(helper) == original_signature


def test_pycollect_makeitem_rewrites_signature_for_injected_parameters() -> None:
    collector = _DummyCollector(is_test_function=True)

    def test_handler(value: int, service: Injected[_Service]) -> tuple[int, _Service]:
        return value, service

    assert tuple(inspect.signature(test_handler).parameters) == ("value", "service")
    result = pytest_pycollect_makeitem(
        collector=collector,
        name="test_handler",
        obj=test_handler,
    )

    assert result is None
    assert tuple(inspect.signature(test_handler).parameters) == ("value",)


def test_pyfunc_call_passes_through_when_no_injected_parameters() -> None:
    def test_handler(value: int) -> int:
        return value

    item = _DummyPyFuncItem(obj=test_handler, container=Container())
    hook = pytest_pyfunc_call(cast("Any", item))
    next(hook)

    assert item.obj is test_handler
    next(hook, None)
    assert item.obj is test_handler


def test_pyfunc_call_wraps_injected_callable_and_restores_original() -> None:
    container = Container()
    default_dependency = _Service("container")
    container.add_instance(default_dependency, provides=_Service)

    def test_handler(service: Injected[_Service]) -> _Service:
        return service

    item = _DummyPyFuncItem(obj=test_handler, container=container)
    hook = pytest_pyfunc_call(cast("Any", item))
    next(hook)

    wrapped = cast("Callable[..., _Service]", item.obj)
    override_dependency = _Service("override")
    assert wrapped() is default_dependency
    assert wrapped(service=override_dependency) is override_dependency

    next(hook, None)
    assert item.obj is test_handler


def test_pyfunc_call_passes_through_when_container_state_is_missing() -> None:
    def test_handler(service: Injected[_Service]) -> _Service:
        return service

    item = _DummyPyFuncItem(obj=test_handler, container=None)
    hook = pytest_pyfunc_call(cast("Any", item))
    next(hook)

    assert item.obj is test_handler
    next(hook, None)
    assert item.obj is test_handler
