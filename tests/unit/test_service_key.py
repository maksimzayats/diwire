"""Tests for ServiceKey and Component classes."""

from typing import Annotated

import pytest

from diwire.service_key import Component, ServiceKey


class TestServiceKeyFromValue:
    def test_from_value_with_type(self) -> None:
        """Basic class type."""

        class ServiceA:
            pass

        key = ServiceKey.from_value(ServiceA)

        assert key.value is ServiceA
        assert key.component is None

    def test_from_value_with_existing_service_key(self) -> None:
        """Returns same ServiceKey when given one."""

        class ServiceA:
            pass

        original = ServiceKey(value=ServiceA)
        result = ServiceKey.from_value(original)

        assert result is original

    def test_from_value_with_annotated_no_component(self) -> None:
        """Annotated[T, Other] without Component."""

        class ServiceA:
            pass

        annotated = Annotated[ServiceA, "some_metadata"]
        key = ServiceKey.from_value(annotated)

        assert key.value is ServiceA
        assert key.component is None

    def test_from_value_with_annotated_and_component(self) -> None:
        """Annotated[T, Component(...)]."""

        class ServiceA:
            pass

        component = Component("test_component")
        annotated = Annotated[ServiceA, component]
        key = ServiceKey.from_value(annotated)

        assert key.value is ServiceA
        assert key.component is component

    def test_from_value_with_annotated_multiple_metadata(self) -> None:
        """Multiple metadata items in Annotated."""

        class ServiceA:
            pass

        component = Component("test")
        annotated = Annotated[ServiceA, "other", component, 123]
        key = ServiceKey.from_value(annotated)

        assert key.value is ServiceA
        assert key.component is component

    def test_from_value_with_none(self) -> None:
        """Handle None as value."""
        key = ServiceKey.from_value(None)

        assert key.value is None
        assert key.component is None

    def test_from_value_with_string(self) -> None:
        """Non-class values."""
        key = ServiceKey.from_value("string_value")

        assert key.value == "string_value"
        assert key.component is None

    def test_from_value_with_function(self) -> None:
        """Function as value."""

        def some_function() -> None:
            pass

        key = ServiceKey.from_value(some_function)

        assert key.value is some_function
        assert key.component is None


class TestServiceKeyEquality:
    def test_equality_same_value(self) -> None:
        """ServiceKey equality with same value."""

        class ServiceA:
            pass

        key1 = ServiceKey(value=ServiceA)
        key2 = ServiceKey(value=ServiceA)

        assert key1 == key2

    def test_equality_different_values(self) -> None:
        """Inequality with different values."""

        class ServiceA:
            pass

        class ServiceB:
            pass

        key1 = ServiceKey(value=ServiceA)
        key2 = ServiceKey(value=ServiceB)

        assert key1 != key2

    def test_equality_with_component(self) -> None:
        """Component affects equality."""

        class ServiceA:
            pass

        key1 = ServiceKey(value=ServiceA, component=Component("a"))
        key2 = ServiceKey(value=ServiceA, component=Component("a"))
        key3 = ServiceKey(value=ServiceA, component=Component("b"))
        key4 = ServiceKey(value=ServiceA)

        assert key1 == key2
        assert key1 != key3
        assert key1 != key4


class TestServiceKeyHash:
    def test_hash_consistency(self) -> None:
        """Same key = same hash."""

        class ServiceA:
            pass

        key1 = ServiceKey(value=ServiceA)
        key2 = ServiceKey(value=ServiceA)

        assert hash(key1) == hash(key2)

    def test_hash_usable_in_dict(self) -> None:
        """Can use as dict key."""

        class ServiceA:
            pass

        key = ServiceKey(value=ServiceA)
        d = {key: "value"}

        assert d[key] == "value"
        assert d[ServiceKey(value=ServiceA)] == "value"

    def test_hash_usable_in_set(self) -> None:
        """Can add to set."""

        class ServiceA:
            pass

        key1 = ServiceKey(value=ServiceA)
        key2 = ServiceKey(value=ServiceA)
        s = {key1, key2}

        assert len(s) == 1

    def test_hash_with_component(self) -> None:
        """Component affects hash."""

        class ServiceA:
            pass

        key1 = ServiceKey(value=ServiceA, component=Component("a"))
        key2 = ServiceKey(value=ServiceA, component=Component("b"))
        s = {key1, key2}

        assert len(s) == 2


class TestServiceKeyImmutability:
    def test_service_key_is_immutable(self) -> None:
        """ServiceKey is frozen."""

        class ServiceA:
            pass

        key = ServiceKey(value=ServiceA)

        with pytest.raises(AttributeError):
            key.value = object()  # type: ignore[misc]

        with pytest.raises(AttributeError):
            key.component = Component("test")  # type: ignore[misc]


class TestComponentCreation:
    def test_component_creation(self) -> None:
        """Basic creation."""
        component = Component("test")

        assert component.value == "test"

    def test_component_equality(self) -> None:
        """Value equality."""
        c1 = Component("test")
        c2 = Component("test")
        c3 = Component("other")

        assert c1 == c2
        assert c1 != c3

    def test_component_hash(self) -> None:
        """Hashable."""
        c1 = Component("test")
        c2 = Component("test")

        assert hash(c1) == hash(c2)
        assert len({c1, c2}) == 1

    def test_component_with_various_values(self) -> None:
        """Component with string, int, tuple."""
        c_str = Component("string")
        c_int = Component(42)
        c_tuple = Component(("a", "b"))

        assert c_str.value == "string"
        assert c_int.value == 42
        assert c_tuple.value == ("a", "b")

    def test_component_is_frozen(self) -> None:
        """Component is immutable."""
        component = Component("test")

        with pytest.raises(AttributeError):
            component.value = "new_value"  # type: ignore[misc]
