"""Tests for types module (Lifetime, Injected, Factory)."""

from enum import Enum
from typing import Annotated, Any, cast, get_args, get_origin

from diwire.exceptions import DIWireInjectedInstantiationError
from diwire.service_key import Component
from diwire.types import Injected, Lifetime, Scope, _InjectedMarker


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
        """Injected is not instantiable."""
        try:
            injected_cls = cast("Any", Injected)
            injected_cls()
        except DIWireInjectedInstantiationError:
            pass
        else:  # pragma: no cover - should always raise
            raise AssertionError("Injected() should raise DIWireInjectedInstantiationError")

    def test_injected_usable_in_annotated(self) -> None:
        """Injected[T] produces Annotated with injected metadata."""

        class ServiceA:
            pass

        annotated = Injected[ServiceA]

        assert get_origin(annotated) is Annotated
        args = get_args(annotated)
        assert args[0] is ServiceA
        assert any(isinstance(arg, _InjectedMarker) for arg in args[1:])

    def test_injected_flattens_annotated(self) -> None:
        """Injected[Annotated[T, Component(...]]] preserves metadata."""

        class ServiceA:
            pass

        annotated = Injected[Annotated[ServiceA, Component("primary")]]

        assert get_origin(annotated) is Annotated
        args = get_args(annotated)
        assert args[0] is ServiceA
        assert any(isinstance(arg, Component) for arg in args[1:])
        assert any(isinstance(arg, _InjectedMarker) for arg in args[1:])


class TestScope:
    def test_scope_app_value(self) -> None:
        """APP has value 'app'."""
        assert Scope.APP.value == "app"

    def test_scope_session_value(self) -> None:
        """SESSION has value 'session'."""
        assert Scope.SESSION.value == "session"

    def test_scope_request_value(self) -> None:
        """REQUEST has value 'request'."""
        assert Scope.REQUEST.value == "request"

    def test_scope_is_enum(self) -> None:
        """Scope is an Enum."""
        assert issubclass(Scope, Enum)

    def test_scope_enum_members(self) -> None:
        """Scope has exactly three members."""
        members = list(Scope)
        assert len(members) == 3
        assert Scope.APP in members
        assert Scope.SESSION in members
        assert Scope.REQUEST in members


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
