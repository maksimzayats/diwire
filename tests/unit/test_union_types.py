"""Tests for union type support in diwire."""

from dataclasses import dataclass
from typing import Union

import pytest

from diwire import Container, Lifetime
from diwire.exceptions import DIWireUnionTypeError


def test_union_type_explicit_registration(container: Container) -> None:
    """Union types work when explicitly registered."""

    @dataclass
    class MyObject:
        value: str = "test"

    @container.register(MyObject | int, lifetime=Lifetime.SINGLETON)  # type: ignore[misc, untyped-decorator]
    def create() -> MyObject | int:
        return MyObject()

    result = container.resolve(MyObject | int)
    assert isinstance(result, MyObject)
    assert result.value == "test"


def test_union_type_without_registration_raises_error(container: Container) -> None:
    """Union types raise clear error when not registered."""
    with pytest.raises(DIWireUnionTypeError) as exc_info:
        container.resolve(str | int)

    assert "union type" in str(exc_info.value).lower()
    assert "explicitly registered" in str(exc_info.value).lower()


def test_union_type_with_typing_union(container: Container) -> None:
    """Union[X, Y] syntax also works."""

    @container.register(  # type: ignore[misc, untyped-decorator]  # pyrefly: ignore[not-callable]
        Union[str, int],  # noqa: UP007
    )
    def create() -> str | int:
        return "hello"

    result = container.resolve(Union[str, int])  # noqa: UP007
    assert result == "hello"


def test_union_type_without_registration_typing_union_raises_error(
    container: Container,
) -> None:
    """Union[X, Y] syntax also raises clear error when not registered."""
    with pytest.raises(DIWireUnionTypeError) as exc_info:
        container.resolve(Union[str, int])  # noqa: UP007

    assert "union type" in str(exc_info.value).lower()
    assert "explicitly registered" in str(exc_info.value).lower()


def test_union_type_singleton_lifetime(container: Container) -> None:
    """Singleton lifetime works with union types."""

    @dataclass
    class MyObject:
        pass

    @container.register(MyObject | None, lifetime=Lifetime.SINGLETON)  # type: ignore[misc, untyped-decorator]
    def create() -> MyObject | None:
        return MyObject()

    obj1 = container.resolve(MyObject | None)
    obj2 = container.resolve(MyObject | None)
    assert obj1 is obj2


def test_union_type_transient_lifetime(container: Container) -> None:
    """Transient lifetime works with union types."""

    @dataclass
    class MyObject:
        pass

    @container.register(MyObject | None, lifetime=Lifetime.TRANSIENT)  # type: ignore[misc, untyped-decorator]
    def create() -> MyObject | None:
        return MyObject()

    obj1 = container.resolve(MyObject | None)
    obj2 = container.resolve(MyObject | None)
    assert obj1 is not obj2


def test_union_type_with_none(container: Container) -> None:
    """Union with None (Optional-like) works correctly."""

    @dataclass
    class Config:
        value: int = 42

    @container.register(Config | None)  # type: ignore[misc, untyped-decorator]  # pyrefly: ignore[not-callable]
    def create() -> Config | None:
        return Config()

    result = container.resolve(Config | None)
    assert isinstance(result, Config)
    assert result.value == 42


def test_union_type_returning_none(container: Container) -> None:
    """Union type factory can return None."""

    @dataclass
    class Config:
        value: int = 42

    @container.register(Config | None, lifetime=Lifetime.SINGLETON)  # type: ignore[misc, untyped-decorator]
    def create() -> Config | None:
        return None

    result = container.resolve(Config | None)
    assert result is None


def test_union_type_inferred_from_return_annotation(container: Container) -> None:
    """Union type inferred from return annotation when no explicit key provided."""

    @dataclass
    class MyObject:
        value: str = "inferred"

    @container.register(lifetime=Lifetime.SINGLETON)
    def create() -> MyObject | int:
        return MyObject()

    result = container.resolve(MyObject | int)
    assert isinstance(result, MyObject)
    assert result.value == "inferred"


def test_union_type_inferred_singleton_behavior(container: Container) -> None:
    """Singleton lifetime works when union type is inferred from return annotation."""

    @dataclass
    class MyObject:
        pass

    @container.register(lifetime=Lifetime.SINGLETON)
    def create() -> MyObject | int:
        return MyObject()

    obj1 = container.resolve(MyObject | int)
    obj2 = container.resolve(MyObject | int)
    assert obj1 is obj2
