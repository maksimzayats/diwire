from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from diwire import All, AsyncProvider, Container, Lifetime, Maybe, Provider, Scope
from diwire.exceptions import DIWireInvalidRegistrationError


@dataclass
class Consumer:
    value: object


@dataclass
class AsyncConsumer:
    value: object


@pytest.mark.parametrize("lifetime", [Lifetime.TRANSIENT, Lifetime.SCOPED])
@pytest.mark.parametrize("key_kind", ["inferred", "explicit", "none_type"])
@pytest.mark.asyncio
async def test_none_instance_resolves_sync_and_async(
    lifetime: Lifetime,
    key_kind: str,
) -> None:
    container = Container(default_lifetime=lifetime)
    key: object
    if key_kind == "inferred":
        container.add_instance(None)
        key = type(None)
    elif key_kind == "none_type":
        container.add_instance(None, provides=type(None))
        key = type(None)
    else:
        container.add_instance(None, provides=object)
        key = object
    resolver = container.compile()
    try:
        for _ in range(3):
            assert resolver.resolve(key) is None
            assert await resolver.aresolve(key) is None
        async with resolver.enter_scope(Scope.REQUEST) as scoped:
            assert scoped.resolve(key) is None
            assert await scoped.aresolve(key) is None
    finally:
        await resolver.aclose()


@pytest.mark.asyncio
async def test_none_instance_is_injected_into_sync_and_async_factories() -> None:
    async def provide_async(value: object) -> AsyncConsumer:
        await asyncio.sleep(0)
        return AsyncConsumer(value)

    container = Container()
    container.add_instance(None, provides=object)
    container.add(Consumer)
    container.add_factory(provide_async)
    resolver = container.compile()
    try:
        assert resolver.resolve(Consumer).value is None
        assert (await resolver.aresolve(Consumer)).value is None
        assert (await resolver.aresolve(AsyncConsumer)).value is None
    finally:
        await resolver.aclose()


@pytest.mark.asyncio
async def test_none_instance_works_with_optional_collection_and_provider_handles() -> None:
    container = Container()
    container.add_instance(None, provides=object)
    container.add_instance(instance=False, provides=object, component="false")
    resolver = container.compile()
    try:
        assert resolver.resolve(Maybe[object]) is None
        assert await resolver.aresolve(Maybe[object]) is None
        assert resolver.resolve(All[object]) == (None, False)
        assert await resolver.aresolve(All[object]) == (None, False)
        assert resolver.resolve(Provider[object])() is None
        handle = await resolver.aresolve(AsyncProvider[object])
        assert await handle() is None
    finally:
        await resolver.aclose()


@pytest.mark.parametrize("value", [False, 0, "", (), []])
@pytest.mark.asyncio
async def test_other_falsy_instances_keep_identity(value: object) -> None:
    container = Container()
    container.add_instance(value, provides=object)
    resolver = container.compile()
    try:
        assert resolver.resolve(object) is value
        assert await resolver.aresolve(object) is value
    finally:
        await resolver.aclose()


@pytest.mark.asyncio
async def test_none_instance_re_registration_replaces_both_directions() -> None:
    container = Container()
    expected = object()
    container.add_instance(None, provides=object)
    assert container.resolve(object) is None
    container.add_instance(expected, provides=object)
    assert container.resolve(object) is expected
    assert await container.aresolve(object) is expected
    container.add_instance(None, provides=object)
    assert container.resolve(object) is None
    assert await container.aresolve(object) is None


@pytest.mark.parametrize("decorate_first", [False, True])
def test_none_instance_survives_decoration_and_spec_copy(*, decorate_first: bool) -> None:
    def decorate(value: object) -> object:
        return {"wrapped": value}

    container = Container()
    if decorate_first:
        container.decorate(provides=object, decorator=decorate)
    container.add_instance(None, provides=object)
    if not decorate_first:
        container.decorate(provides=object, decorator=decorate)
    assert container.resolve(object) == {"wrapped": None}


def test_none_dependency_key_is_still_rejected() -> None:
    container = Container()
    with pytest.raises(DIWireInvalidRegistrationError, match=r"provides.*must not be None"):
        container.add_instance(None, provides=None)
