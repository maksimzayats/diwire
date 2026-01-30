"""Tests for types module (Lifetime, Injected, Factory)."""

from enum import Enum
from typing import Annotated, get_args, get_origin

from diwire.types import Injected, Lifetime


class TestLifetime:
    def test_lifetime_transient_value(self) -> None:
        """TRANSIENT has value 'transient'."""
        assert Lifetime.TRANSIENT.value == "transient"

    def test_lifetime_singleton_value(self) -> None:
        """SINGLETON has value 'singleton'."""
        assert Lifetime.SINGLETON.value == "singleton"

    def test_lifetime_scoped_value(self) -> None:
        """SCOPED has value 'scoped'."""
        assert Lifetime.SCOPED.value == "scoped"

    def test_lifetime_is_enum(self) -> None:
        """Lifetime is an Enum."""
        assert issubclass(Lifetime, Enum)

    def test_lifetime_enum_members(self) -> None:
        """Lifetime has exactly three members."""
        members = list(Lifetime)
        assert len(members) == 3
        assert Lifetime.TRANSIENT in members
        assert Lifetime.SINGLETON in members
        assert Lifetime.SCOPED in members


class TestInjected:
    def test_injected_instantiation(self) -> None:
        """Injected can be instantiated."""
        marker = Injected()
        assert isinstance(marker, Injected)

    def test_injected_multiple_instances(self) -> None:
        """Multiple Injected instances are independent."""
        marker1 = Injected()
        marker2 = Injected()

        # They are different objects
        assert marker1 is not marker2

    def test_injected_usable_in_annotated(self) -> None:
        """Injected can be used in Annotated."""

        class ServiceA:
            pass

        annotated = Annotated[ServiceA, Injected()]

        assert get_origin(annotated) is Annotated
        args = get_args(annotated)
        assert args[0] is ServiceA
        assert isinstance(args[1], Injected)


class TestFactoryProtocol:
    def test_factory_class_protocol_compliance(self) -> None:
        """Class conforming to FactoryClassProtocol."""

        class ServiceA:
            pass

        class MyFactory:
            def __call__(self) -> ServiceA:
                return ServiceA()

        factory = MyFactory()
        result = factory()

        assert isinstance(result, ServiceA)

    def test_factory_function_callable(self) -> None:
        """Function as factory."""

        class ServiceA:
            pass

        def my_factory() -> ServiceA:
            return ServiceA()

        result = my_factory()

        assert isinstance(result, ServiceA)
