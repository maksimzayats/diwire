from __future__ import annotations

import pytest

from diwire import Container, Injected, Lifetime

pytest_plugins = ["diwire.integrations.pytest_plugin"]


class _Service:
    pass


class _FakeService(_Service):
    pass


@pytest.fixture()
def diwire_container() -> Container:
    container = Container()
    container.add_concrete(
        _FakeService,
        provides=_Service,
        lifetime=Lifetime.SCOPED,
    )
    return container


@pytest.fixture()
def value() -> int:
    return 42


def test_injected_parameters_are_resolved_from_diwire_container(
    value: int,
    service: Injected[_Service],
) -> None:
    assert value == 42
    assert isinstance(service, _FakeService)


@pytest.mark.asyncio
async def test_async_test_functions_support_injected_parameters(
    service: Injected[_Service],
) -> None:
    assert isinstance(service, _FakeService)


def test_regular_fixture_resolution_still_works_without_injected_parameters(value: int) -> None:
    assert value == 42


def test_public_diwire_container_fixture_is_available(diwire_container: Container) -> None:
    assert isinstance(diwire_container, Container)
