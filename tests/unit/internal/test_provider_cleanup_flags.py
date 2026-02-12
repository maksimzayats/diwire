from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from diwire import Container


class Service:
    pass


class Resource:
    pass


def test_container_sets_cleanup_flag_for_context_manager_provider() -> None:
    @contextmanager
    def provide_resource() -> Generator[Resource, None, None]:
        yield Resource()

    container = Container()
    container.add_context_manager(provide_resource)
    spec = container._providers_registrations.get_by_type(Resource)

    assert spec.needs_cleanup


def test_container_sets_cleanup_flag_for_dependency_cleanup() -> None:
    def provide_service(resource: Resource) -> Service:
        return Service()

    @contextmanager
    def provide_resource() -> Generator[Resource, None, None]:
        yield Resource()

    container = Container()
    container.add_context_manager(provide_resource)
    container.add_factory(provide_service)
    spec = container._providers_registrations.get_by_type(Service)

    assert spec.needs_cleanup


def test_container_updates_cleanup_flag_when_dependency_registered_later() -> None:
    def provide_service(resource: Resource) -> Service:
        return Service()

    @contextmanager
    def provide_resource() -> Generator[Resource, None, None]:
        yield Resource()

    container = Container()
    container.add_factory(provide_service)
    service_spec = container._providers_registrations.get_by_type(Service)
    assert not service_spec.needs_cleanup

    container.add_context_manager(provide_resource)
    updated_service_spec = container._providers_registrations.get_by_type(Service)

    assert updated_service_spec.needs_cleanup
