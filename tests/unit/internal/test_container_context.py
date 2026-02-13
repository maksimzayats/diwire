from __future__ import annotations

from typing import Any, cast

import pytest

import diwire
from diwire import Container, FromContext, Injected, ProviderContext, Scope
from diwire.exceptions import DIWireInvalidRegistrationError, DIWireProviderNotSetError


class _Service:
    def __init__(self, value: str) -> None:
        self.value = value


def test_top_level_provider_context_export_is_available() -> None:
    assert isinstance(diwire.provider_context, ProviderContext)


def test_resolve_raises_when_no_bound_resolver_and_no_fallback_container() -> None:
    context = ProviderContext()

    with pytest.raises(DIWireProviderNotSetError, match="provider_context"):
        context.resolve(_Service)


@pytest.mark.asyncio
async def test_aresolve_raises_when_no_bound_resolver_and_no_fallback_container() -> None:
    context = ProviderContext()

    with pytest.raises(DIWireProviderNotSetError, match="provider_context"):
        await context.aresolve(_Service)


def test_enter_scope_raises_when_no_bound_resolver_and_no_fallback_container() -> None:
    context = ProviderContext()

    with pytest.raises(DIWireProviderNotSetError, match="provider_context"):
        context.enter_scope(Scope.REQUEST)


def test_resolve_uses_fallback_container_when_unbound() -> None:
    context = ProviderContext()
    container = Container(provider_context=context)
    container.add_instance(_Service("fallback"), provides=_Service)

    assert context.resolve(_Service).value == "fallback"


@pytest.mark.asyncio
async def test_aresolve_uses_fallback_container_when_unbound() -> None:
    context = ProviderContext()
    container = Container(provider_context=context)
    container.add_instance(_Service("fallback"), provides=_Service)

    assert (await context.aresolve(_Service)).value == "fallback"


def test_enter_scope_uses_fallback_container_when_unbound() -> None:
    context = ProviderContext()
    container = Container(provider_context=context)
    container.add_instance(_Service("fallback"), provides=_Service)

    with context.enter_scope(Scope.REQUEST) as request_scope:
        assert request_scope.resolve(_Service).value == "fallback"
        with context.enter_scope(Scope.ACTION) as action_scope:
            assert action_scope.resolve(_Service).value == "fallback"
            with context.enter_scope(Scope.STEP) as step_scope:
                assert step_scope.resolve(_Service).value == "fallback"


def test_last_container_wins_for_fallback_resolve_and_enter_scope() -> None:
    context = ProviderContext()
    first = Container(provider_context=context)
    first.add_instance(_Service("first"), provides=_Service)
    second = Container(provider_context=context)
    second.add_instance(_Service("second"), provides=_Service)

    assert context.resolve(_Service).value == "second"
    with context.enter_scope(Scope.REQUEST) as request_scope:
        assert request_scope.resolve(_Service).value == "second"


@pytest.mark.asyncio
async def test_last_container_wins_for_fallback_aresolve() -> None:
    context = ProviderContext()
    first = Container(provider_context=context)
    first.add_instance(_Service("first"), provides=_Service)
    second = Container(provider_context=context)
    second.add_instance(_Service("second"), provides=_Service)

    assert (await context.aresolve(_Service)).value == "second"


def test_inject_raises_when_no_resolver_and_no_fallback_container() -> None:
    context = ProviderContext()

    @context.inject
    def handler(service: Injected[_Service]) -> str:
        return service.value

    with pytest.raises(DIWireProviderNotSetError, match=r"provider_context\.inject"):
        cast("Any", handler)()


def test_inject_explicit_resolver_still_requires_fallback_container() -> None:
    context = ProviderContext()
    resolver = Container().compile()

    @context.inject
    def handler(service: Injected[_Service]) -> str:
        return service.value

    with pytest.raises(DIWireProviderNotSetError, match="fallback container"):
        cast("Any", handler)(diwire_resolver=resolver)


def test_inject_uses_fallback_container_when_unbound() -> None:
    context = ProviderContext()
    container = Container(provider_context=context)
    container.add_instance(_Service("fallback"), provides=_Service)

    @context.inject
    def handler(service: Injected[_Service]) -> str:
        return service.value

    assert cast("Any", handler)() == "fallback"


def test_last_container_wins_for_fallback_inject() -> None:
    context = ProviderContext()
    first = Container(provider_context=context)
    first.add_instance(_Service("first"), provides=_Service)
    second = Container(provider_context=context)
    second.add_instance(_Service("second"), provides=_Service)

    @context.inject
    def handler(service: Injected[_Service]) -> str:
        return service.value

    assert cast("Any", handler)() == "second"


def test_context_bound_resolver_takes_precedence_over_fallback_container() -> None:
    context = ProviderContext()
    first = Container(provider_context=context)
    first.add_instance(_Service("first"), provides=_Service)
    second = Container(provider_context=context)
    second.add_instance(_Service("second"), provides=_Service)

    @context.inject
    def handler(service: Injected[_Service]) -> str:
        return service.value

    assert cast("Any", handler)() == "second"

    with first.compile():
        assert cast("Any", handler)() == "first"


def test_context_bound_resolver_takes_precedence_over_fallback_for_resolve_and_enter_scope() -> (
    None
):
    context = ProviderContext()
    first = Container(provider_context=context)
    first.add_instance(_Service("first"), provides=_Service)
    second = Container(provider_context=context)
    second.add_instance(_Service("second"), provides=_Service)

    assert context.resolve(_Service).value == "second"
    with context.enter_scope(Scope.REQUEST) as request_scope:
        assert request_scope.resolve(_Service).value == "second"

    with first.compile():
        assert context.resolve(_Service).value == "first"
        with context.enter_scope(Scope.REQUEST) as request_scope:
            assert request_scope.resolve(_Service).value == "first"

    assert context.resolve(_Service).value == "second"


@pytest.mark.asyncio
async def test_context_bound_resolver_takes_precedence_over_fallback_for_aresolve() -> None:
    context = ProviderContext()
    first = Container(provider_context=context)
    first.add_instance(_Service("first"), provides=_Service)
    second = Container(provider_context=context)
    second.add_instance(_Service("second"), provides=_Service)

    assert (await context.aresolve(_Service)).value == "second"

    async with first.compile():
        assert (await context.aresolve(_Service)).value == "first"

    assert (await context.aresolve(_Service)).value == "second"


def test_nested_sync_context_manager_restores_previous_resolver() -> None:
    context = ProviderContext()
    first = Container(provider_context=context)
    first.add_instance("first", provides=str)
    second = Container(provider_context=context)
    second.add_instance("second", provides=str)

    with first.compile():
        assert context.resolve(str) == "first"
        with second.compile():
            assert context.resolve(str) == "second"
        assert context.resolve(str) == "first"

    assert context.resolve(str) == "second"


@pytest.mark.asyncio
async def test_nested_async_context_manager_restores_previous_resolver() -> None:
    context = ProviderContext()
    first = Container(provider_context=context)
    first.add_instance("first", provides=str)
    second = Container(provider_context=context)
    second.add_instance("second", provides=str)

    async with first.compile():
        assert await context.aresolve(str) == "first"
        async with second.compile():
            assert await context.aresolve(str) == "second"
        assert await context.aresolve(str) == "first"

    assert context.resolve(str) == "second"


def test_fallback_scope_binding_works_when_container_disables_provider_context() -> None:
    context = ProviderContext()
    container = Container(provider_context=context, use_provider_context=False)
    container.add_instance(_Service("fallback"), provides=_Service)

    assert context.resolve(_Service).value == "fallback"

    with context.enter_scope(Scope.REQUEST) as request_scope:
        assert request_scope.resolve(_Service).value == "fallback"
        with context.enter_scope(Scope.ACTION) as action_scope:
            assert action_scope.resolve(_Service).value == "fallback"


def test_inject_rejects_reserved_resolver_parameter_name() -> None:
    context = ProviderContext()

    with pytest.raises(DIWireInvalidRegistrationError, match="cannot declare reserved parameter"):

        @context.inject
        def _handler(diwire_resolver: object, /, service: Injected[_Service]) -> None:
            _ = service


def test_inject_rejects_reserved_context_parameter_name() -> None:
    context = ProviderContext()

    with pytest.raises(DIWireInvalidRegistrationError, match="cannot declare reserved parameter"):

        @context.inject
        def _handler(diwire_context: object, /, service: Injected[_Service]) -> None:
            _ = service


def test_inject_forwards_context_kwarg_and_validates_scope_usage() -> None:
    context = ProviderContext()
    container = Container(provider_context=context)

    @context.inject(scope=Scope.REQUEST)
    def handler(value: FromContext[int]) -> int:
        return value

    injected_handler = cast("Any", handler)
    assert injected_handler(diwire_context={int: 7}) == 7

    @context.inject(auto_open_scope=False)
    def no_scope(value: FromContext[int]) -> int:
        return value

    no_scope_handler = cast("Any", no_scope)
    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="was provided but no new scope was opened",
    ):
        no_scope_handler(diwire_context={int: 9})
