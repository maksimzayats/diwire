from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Iterator
from contextlib import suppress
from typing import Any, cast

import pytest

from diwire._internal.container import Container
from diwire._internal.injection import (
    INJECT_RESOLVER_KWARG,
    InjectedCallableInspector,
    InjectedParameter,
)
from diwire._internal.resolver_context import resolver_context

_DIWIRE_CONTAINER_ATTR = "_diwire_container"
_DIWIRE_INJECTED_PARAMETERS_ATTR = "__diwire_pytest_injected_parameters__"
_DIWIRE_ORIGINAL_SIGNATURE_ATTR = "__diwire_pytest_original_signature__"
_INJECTED_CALLABLE_INSPECTOR = InjectedCallableInspector()


@pytest.fixture()
def diwire_container() -> Container:
    """Fixture hook for the plugin-managed test container.

    Users must override this fixture in their own test suite to provide
    registrations for injected dependencies.

    """
    msg = (
        "The diwire pytest plugin requires overriding the 'diwire_container' fixture in your "
        "test suite. Define @pytest.fixture() def diwire_container() -> Container: ... "
        "and return a configured container."
    )
    raise RuntimeError(msg)


@pytest.fixture(autouse=True)
def _diwire_state(
    request: pytest.FixtureRequest,
    diwire_container: Container,
) -> None:
    """Store plugin state on the test node for hook access."""
    node = cast("Any", request.node)
    setattr(node, _DIWIRE_CONTAINER_ATTR, diwire_container)


def pytest_pycollect_makeitem(
    collector: Any,
    name: str,
    obj: object,
) -> Any | None:
    """Hide ``Injected[...]`` parameters from pytest fixture name matching.

    Pytest treats test function parameters as fixture names. This hook rewrites
    signatures for callables that use DIWire injection metadata so injected
    parameters are not interpreted as missing fixtures.

    Args:
        collector: Pytest collector instance.
        name: Collected object name.
        obj: Candidate object.

    Returns:
        ``None`` to continue default collection flow.

    """
    if not callable(obj):
        return None
    if not collector.istestfunction(obj, name):
        return None

    callable_obj = cast("Callable[..., Any]", obj)
    inspection = _INJECTED_CALLABLE_INSPECTOR.inspect_callable(callable_obj)
    if not inspection.injected_parameters:
        return None

    obj_as_any = cast("Any", obj)
    obj_as_any.__dict__[_DIWIRE_INJECTED_PARAMETERS_ATTR] = inspection.injected_parameters
    obj_as_any.__dict__[_DIWIRE_ORIGINAL_SIGNATURE_ATTR] = inspection.signature
    obj_as_any.__signature__ = inspection.public_signature
    return None


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> Iterator[None]:
    """Wrap test function execution to resolve ``Injected[...]`` parameters.

    The wrapper swaps the callable with ``resolver_context.inject(original_callable)``
    for the duration of the test call and executes with an explicit resolver
    kwarg. If no container state is attached to the node, this hook is a no-op.

    Limitations:
        Injection requires a callable test object and plugin-managed state on the
        test item. Non-function collection paths are ignored.

    Args:
        pyfuncitem: Collected pytest function item.

    Yields:
        Control back to pytest around test execution.

    """
    original_callable = cast("Callable[..., Any]", pyfuncitem.obj)
    original_callable_as_any = cast("Any", original_callable)
    injected_parameters = cast(
        "tuple[InjectedParameter, ...] | None",
        getattr(original_callable_as_any, _DIWIRE_INJECTED_PARAMETERS_ATTR, None),
    )
    if injected_parameters is None:
        injected_parameters = _INJECTED_CALLABLE_INSPECTOR.inspect_callable(
            original_callable,
        ).injected_parameters
    if not injected_parameters:
        yield
        return

    item = cast("Any", pyfuncitem)
    container = cast("Container | None", getattr(item, _DIWIRE_CONTAINER_ATTR, None))
    if container is None:
        yield
        return

    had_signature_override = hasattr(original_callable_as_any, "__signature__")
    signature_override = cast("Any", getattr(original_callable_as_any, "__signature__", None))
    original_signature = cast(
        "inspect.Signature | None",
        getattr(original_callable_as_any, _DIWIRE_ORIGINAL_SIGNATURE_ATTR, None),
    )
    if original_signature is not None:
        original_callable_as_any.__signature__ = original_signature

    try:
        injected_callable = resolver_context.inject(original_callable)
        resolver = container.compile()
        if inspect.iscoroutinefunction(injected_callable):

            @functools.wraps(injected_callable)
            async def _invoke_with_resolver(*args: Any, **kwargs: Any) -> Any:
                kwargs[INJECT_RESOLVER_KWARG] = resolver
                return await cast("Any", injected_callable)(*args, **kwargs)

        else:

            @functools.wraps(injected_callable)
            def _invoke_with_resolver(*args: Any, **kwargs: Any) -> Any:
                kwargs[INJECT_RESOLVER_KWARG] = resolver
                return injected_callable(*args, **kwargs)

        pyfuncitem.obj = _invoke_with_resolver
    finally:
        if had_signature_override:
            original_callable_as_any.__signature__ = signature_override
        else:
            with suppress(AttributeError):
                del original_callable_as_any.__signature__

    try:
        yield
    finally:
        pyfuncitem.obj = original_callable
