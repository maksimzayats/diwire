import pytest

from diwire import Container, IContainer, Injected, container_context


def test_container_is_icontainer() -> None:
    container = Container()
    assert isinstance(container, IContainer)
    assert issubclass(Container, IContainer)


def test_container_context_is_icontainer() -> None:
    assert isinstance(container_context, IContainer)
    assert issubclass(type(container_context), IContainer)


def test_scoped_container_is_icontainer() -> None:
    container = Container()
    with container.enter_scope("request") as scope:
        assert isinstance(scope, IContainer)
        assert issubclass(type(scope), IContainer)


def test_scoped_container_delegates_register_compile_and_resolve() -> None:
    container = Container(autoregister=False)

    class Service:
        pass

    service = Service()

    def handler(dep: Injected[Service]) -> Service:
        return dep

    with container.enter_scope("request") as scope:
        scope.register(Service, instance=service)
        scope.compile()
        assert scope.resolve(Service) is service

        decorated = scope.resolve()(handler)
        assert decorated() is service

        scoped_handler = scope.resolve(handler, scope="request")
        assert scoped_handler() is service


def test_scoped_container_close_scope() -> None:
    container = Container()
    with container.enter_scope("request") as scope:
        scope.close_scope("request")


@pytest.mark.asyncio
async def test_scoped_container_aresolve_with_scope() -> None:
    container = Container(autoregister=False)

    class Service:
        pass

    service = Service()
    container.register(Service, instance=service)

    async def handler(dep: Injected[Service]) -> Service:
        return dep

    with container.enter_scope("request") as scope:
        scoped_handler = await scope.aresolve(handler, scope="request")
        assert await scoped_handler() is service


@pytest.mark.asyncio
async def test_scoped_container_aclose_scope() -> None:
    container = Container()
    async with container.enter_scope("request") as scope:
        await scope.aclose_scope("request")
