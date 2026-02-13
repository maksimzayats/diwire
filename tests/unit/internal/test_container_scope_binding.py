from __future__ import annotations

import pytest

from diwire import Container, FromContext, Lifetime, Scope
from diwire.exceptions import DIWireDependencyNotRegisteredError, DIWireScopeMismatchError


class _RequestOnly:
    pass


class _ActionFromContext:
    def __init__(self, value: FromContext[int]) -> None:
        self.value = value


class _AsyncRequestOnly:
    pass


def test_container_resolve_uses_context_bound_scope_by_default() -> None:
    container = Container()
    container.add(
        _RequestOnly,
        provides=_RequestOnly,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.REQUEST):
        assert isinstance(container.resolve(_RequestOnly), _RequestOnly)


@pytest.mark.asyncio
async def test_container_aresolve_uses_context_bound_scope_by_default() -> None:
    container = Container()

    async def build() -> _AsyncRequestOnly:
        return _AsyncRequestOnly()

    container.add_factory(
        build,
        provides=_AsyncRequestOnly,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.REQUEST):
        assert isinstance(await container.aresolve(_AsyncRequestOnly), _AsyncRequestOnly)


def test_container_resolve_does_not_use_context_bound_scope_when_disabled() -> None:
    container = Container(use_resolver_context=False)
    container.add(
        _RequestOnly,
        provides=_RequestOnly,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.REQUEST):
        with pytest.raises(DIWireScopeMismatchError, match="requires opened scope level"):
            _ = container.resolve(_RequestOnly)


def test_container_enter_scope_uses_context_bound_scope_for_nesting() -> None:
    container = Container()
    container.add(
        _ActionFromContext,
        provides=_ActionFromContext,
        scope=Scope.ACTION,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.REQUEST, context={int: 7}):
        with container.enter_scope(Scope.ACTION):
            assert container.resolve(_ActionFromContext).value == 7


def test_container_enter_scope_without_nesting_does_not_inherit_context() -> None:
    container = Container(use_resolver_context=False)
    container.add(
        _ActionFromContext,
        provides=_ActionFromContext,
        scope=Scope.ACTION,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.REQUEST, context={int: 7}):
        with container.enter_scope(Scope.ACTION) as action_resolver:
            with pytest.raises(DIWireDependencyNotRegisteredError, match="Context value"):
                _ = action_resolver.resolve(_ActionFromContext)
