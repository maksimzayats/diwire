"""Tests for Registration dataclass."""

from diwire.registry import Registration
from diwire.service_key import ServiceKey
from diwire.types import Lifetime


class ServiceA:
    pass


class TestRegistrationCreation:
    def test_registration_creation_with_all_fields(self) -> None:
        """Create Registration with all fields."""
        service_key = ServiceKey(value=ServiceA)

        def factory() -> ServiceA:
            return ServiceA()

        instance = ServiceA()

        registration = Registration(
            service_key=service_key,
            lifetime=Lifetime.SINGLETON,
            factory=factory,
            instance=instance,
        )

        assert registration.service_key is service_key
        assert registration.lifetime == Lifetime.SINGLETON
        assert registration.factory is factory
        assert registration.instance is instance

    def test_registration_defaults(self) -> None:
        """Create Registration with only required fields."""
        service_key = ServiceKey(value=ServiceA)

        registration = Registration(
            service_key=service_key,
            lifetime=Lifetime.TRANSIENT,
        )

        assert registration.service_key is service_key
        assert registration.lifetime == Lifetime.TRANSIENT
        assert registration.factory is None
        assert registration.instance is None

    def test_registration_with_factory_only(self) -> None:
        """Create Registration with factory only."""
        service_key = ServiceKey(value=ServiceA)

        def factory() -> ServiceA:
            return ServiceA()

        registration = Registration(
            service_key=service_key,
            lifetime=Lifetime.TRANSIENT,
            factory=factory,
        )

        assert registration.factory is factory
        assert registration.instance is None

    def test_registration_with_instance_only(self) -> None:
        """Create Registration with instance only."""
        service_key = ServiceKey(value=ServiceA)
        instance = ServiceA()

        registration = Registration(
            service_key=service_key,
            lifetime=Lifetime.SINGLETON,
            instance=instance,
        )

        assert registration.factory is None
        assert registration.instance is instance


class TestRegistrationEquality:
    def test_registration_equality(self) -> None:
        """Registration equality."""
        service_key = ServiceKey(value=ServiceA)

        reg1 = Registration(service_key=service_key, lifetime=Lifetime.TRANSIENT)
        reg2 = Registration(service_key=service_key, lifetime=Lifetime.TRANSIENT)
        reg3 = Registration(service_key=service_key, lifetime=Lifetime.SINGLETON)

        assert reg1 == reg2
        assert reg1 != reg3
