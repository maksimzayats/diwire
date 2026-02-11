from __future__ import annotations

import pytest

from diwire import Container, Injected, Lifetime

pytest_plugins = ["diwire.integrations.pytest_plugin"]


class Service:
    pass


class ServiceImpl(Service):
    pass


@pytest.fixture()
def diwire_container() -> Container:
    container = Container(autoregister_concrete_types=False)
    container.register_concrete(
        Service,
        concrete_type=ServiceImpl,
        lifetime=Lifetime.SCOPED,
    )
    return container


def test_plugin_injects_parameters(service: Injected[Service]) -> None:
    if not isinstance(service, ServiceImpl):
        msg = "Injected service is not ServiceImpl"
        raise TypeError(msg)
