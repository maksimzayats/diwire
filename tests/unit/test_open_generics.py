import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Generic, TypeVar, cast

import pytest

from diwire.container import Container
from diwire.container_helpers import _type_arg_matches_constraint
from diwire.exceptions import (
    DIWireInvalidGenericTypeArgumentError,
    DIWireOpenGenericRegistrationError,
    DIWireOpenGenericResolutionError,
)
from diwire.registry import Registration
from diwire.service_key import ServiceKey
from diwire.types import Lifetime

T = TypeVar("T")
U = TypeVar("U")


class Model:
    pass


M = TypeVar("M", bound=Model)
C = TypeVar("C", list[int], dict[str, int])


def test_open_generic_factory_decorator(container: Container) -> None:
    @dataclass
    class Box(Generic[T]):
        value: str

    if TYPE_CHECKING:
        box_key = Box[Any]
    else:
        box_key = Box[T]

    decorator = cast(
        "Callable[[Callable[..., object]], Callable[..., object]]",
        container.register(box_key),
    )

    def create_box(type_arg: Annotated[type[T], "meta"]) -> Box[T]:
        return Box(value=type_arg.__name__)

    decorator(create_box)

    assert container.resolve(Box[int]).value == "int"
    assert container.resolve(Box[str]).value == "str"


@pytest.mark.asyncio
async def test_open_generic_async_factory(container: Container) -> None:
    @dataclass
    class AsyncBox(Generic[T]):
        value: str

    if TYPE_CHECKING:
        box_key = AsyncBox[Any]
    else:
        box_key = AsyncBox[T]

    decorator = cast(
        "Callable[[Callable[..., object]], Callable[..., object]]",
        container.register(box_key),
    )

    async def create_box(type_arg: type[T]) -> AsyncBox[T]:
        return AsyncBox(value=type_arg.__name__)

    decorator(create_box)

    result = await container.aresolve(AsyncBox[int])
    assert result.value == "int"


def test_open_generic_resolution_requires_concrete_args(container: Container) -> None:
    @dataclass
    class Box(Generic[T]):
        value: str

    if TYPE_CHECKING:
        box_key = Box[Any]
    else:
        box_key = Box[T]

    decorator = cast(
        "Callable[[Callable[..., object]], Callable[..., object]]",
        container.register(box_key),
    )

    def create_box(type_arg: type[T]) -> Box[T]:
        return Box(value=type_arg.__name__)

    decorator(create_box)

    with pytest.raises(DIWireOpenGenericResolutionError):
        container.resolve(box_key)


def test_open_generic_arity_mismatch(container: Container) -> None:
    @dataclass
    class Pair(Generic[T, U]):
        left: object | None = None
        right: object | None = None

    if TYPE_CHECKING:
        pair_key = Pair[Any, Any]
    else:
        pair_key = Pair[T, U]

    decorator = cast(
        "Callable[[Callable[..., object]], Callable[..., object]]",
        container.register(pair_key),
    )

    def create_pair() -> Pair[T, U]:
        return Pair()

    decorator(create_pair)

    pair_any = cast("Any", types.GenericAlias(Pair, (int,)))
    with pytest.raises(DIWireOpenGenericResolutionError) as excinfo:
        container.resolve(pair_any)
    assert "Expected 2 type argument(s), got 1." in str(excinfo.value)


def test_type_arg_matches_constraint_any() -> None:
    assert _type_arg_matches_constraint(Any, int) is True
    assert _type_arg_matches_constraint(int, Any) is True


def test_type_arg_matches_constraint_typeerror() -> None:
    class ExplodingMeta(type):
        def __subclasscheck__(cls, subclass: type) -> bool:
            raise TypeError("boom")

    class Exploding(metaclass=ExplodingMeta):
        pass

    assert _type_arg_matches_constraint(int, Exploding) is False


def test_type_arg_matches_constraint_generic_alias_different_origin() -> None:
    """Test that generic aliases with different origins don't match."""
    assert _type_arg_matches_constraint(list[int], dict[str, int]) is False


def test_type_arg_matches_constraint_generic_alias_different_arity() -> None:
    """Test that generic aliases with same origin but different arity don't match."""
    assert _type_arg_matches_constraint(tuple[int], tuple[int, str]) is False


def test_type_arg_matches_constraint_non_generic_fallback() -> None:
    """Test fallback equality for non-generic, non-type values."""
    assert _type_arg_matches_constraint("foo", "foo") is True
    assert _type_arg_matches_constraint("foo", "bar") is False


def test_open_generic_instance_registration_error(container: Container) -> None:
    @dataclass
    class Box(Generic[T]):
        value: str

    if TYPE_CHECKING:
        box_key = Box[Any]
    else:
        box_key = Box[T]

    with pytest.raises(DIWireOpenGenericRegistrationError):
        container.register(box_key, instance=Box(value="x"))


def test_open_generic_concrete_class_unsupported(container: Container) -> None:
    @dataclass
    class Box(Generic[T]):
        value: str

    class Concrete:
        pass

    if TYPE_CHECKING:
        box_key = Box[Any]
    else:
        box_key = Box[T]

    with pytest.raises(DIWireOpenGenericRegistrationError):
        container.register(box_key, concrete_class=Concrete)


def test_open_generic_partial_registration_error(container: Container) -> None:
    @dataclass
    class Pair(Generic[T, U]):
        left: object | None = None
        right: object | None = None

    if TYPE_CHECKING:
        pair_key = Pair[Any, int]
    else:
        pair_key = Pair[T, int]

    with pytest.raises(DIWireOpenGenericRegistrationError):
        container.register(pair_key, factory=lambda: Pair())


def test_open_generic_bound_validation(container: Container) -> None:
    class User(Model):
        pass

    @dataclass
    class ModelBox(Generic[M]):
        model: M

    if TYPE_CHECKING:
        box_key = ModelBox[Any]
    else:
        box_key = ModelBox[M]

    decorator = cast(
        "Callable[[Callable[..., object]], Callable[..., object]]",
        container.register(box_key),
    )

    def create_box(model_cls: type[M]) -> ModelBox[M]:
        return ModelBox(model=model_cls())

    decorator(create_box)

    assert isinstance(container.resolve(ModelBox[User]).model, User)
    with pytest.raises(DIWireInvalidGenericTypeArgumentError):
        model_box_any = cast("Any", ModelBox)
        container.resolve(model_box_any[str])


def test_open_generic_constraints_validation(container: Container) -> None:
    @dataclass
    class Constrained(Generic[C]):
        pass

    if TYPE_CHECKING:
        constrained_key = Constrained[Any]
    else:
        constrained_key = Constrained[C]

    decorator = cast(
        "Callable[[Callable[..., object]], Callable[..., object]]",
        container.register(constrained_key),
    )

    def create_constrained() -> Constrained[C]:
        return Constrained()

    decorator(create_constrained)

    assert isinstance(container.resolve(Constrained[list[int]]), Constrained)
    with pytest.raises(DIWireInvalidGenericTypeArgumentError):
        constrained_any = cast("Any", Constrained)
        container.resolve(constrained_any[set[int]])


def test_open_generic_default_typevar_dependency(container: Container) -> None:
    @dataclass
    class Box(Generic[T]):
        value: str

    if TYPE_CHECKING:
        box_key = Box[Any]
    else:
        box_key = Box[T]

    decorator = cast(
        "Callable[[Callable[..., object]], Callable[..., object]]",
        container.register(box_key),
    )

    default_type_arg: Any = str

    def create_box(type_arg: type[U] = default_type_arg) -> Box[T]:  # type: ignore[assignment]
        return Box(value=type_arg.__name__)

    decorator(create_box)

    assert container.resolve(Box[int]).value == "str"


def test_open_generic_missing_typevar_mapping(container: Container) -> None:
    class Weird(Generic[T]):
        pass

    if TYPE_CHECKING:
        weird_key = Weird[Any]
    else:
        weird_key = Weird[T]

    decorator = cast(
        "Callable[[Callable[..., object]], Callable[..., object]]",
        container.register(weird_key),
    )

    def create_weird(cls: type[U]) -> Weird[T]:
        return Weird()

    decorator(create_weird)

    with pytest.raises(DIWireOpenGenericResolutionError):
        container.resolve(Weird[int])


def test_open_generic_resolution_in_anonymous_scope(container: Container) -> None:
    @dataclass
    class Box(Generic[T]):
        value: str

    if TYPE_CHECKING:
        box_key = Box[Any]
    else:
        box_key = Box[T]

    decorator = cast(
        "Callable[[Callable[..., object]], Callable[..., object]]",
        container.register(box_key),
    )

    def create_box(type_arg: type[T]) -> Box[T]:
        return Box(value=type_arg.__name__)

    decorator(create_box)

    with container.enter_scope():
        assert container.resolve(Box[int]).value == "int"


def test_scoped_open_generic_registration_skips_anonymous_scope(
    container: Container,
) -> None:
    class Box(Generic[T]):
        pass

    with container.enter_scope() as scope:
        result = container._get_scoped_open_generic_registration(
            Box,
            None,
            scope._scope_id,
        )

    assert result is None


def test_open_generic_scoped_singleton(container: Container) -> None:
    @dataclass
    class ScopedBox(Generic[T]):
        value: int = 0

    if TYPE_CHECKING:
        scoped_key = ScopedBox[Any]
    else:
        scoped_key = ScopedBox[T]

    decorator = cast(
        "Callable[[Callable[..., object]], Callable[..., object]]",
        container.register(
            scoped_key,
            lifetime=Lifetime.SCOPED,
            scope="request",
        ),
    )

    def create_box() -> ScopedBox[T]:
        return ScopedBox()

    decorator(create_box)

    with container.enter_scope("request"):
        first = container.resolve(ScopedBox[int])
        second = container.resolve(ScopedBox[int])
        assert first is second


def test_compile_skips_typevar_dependencies(container: Container) -> None:
    class TypevarInit(Generic[T]):
        def __init__(self, kind: type[T]) -> None:
            self.kind = kind

    container.register(TypevarInit)
    container.compile()

    service_key = ServiceKey.from_value(TypevarInit)
    assert service_key not in container._compiled_providers


def test_compile_skips_typevar_map_registrations(container: Container) -> None:
    @dataclass
    class Box(Generic[T]):
        value: str

    if TYPE_CHECKING:
        box_key = Box[Any]
    else:
        box_key = Box[T]

    decorator = cast(
        "Callable[[Callable[..., object]], Callable[..., object]]",
        container.register(box_key),
    )

    def create_box(type_arg: type[T]) -> Box[T]:
        return Box(value=type_arg.__name__)

    decorator(create_box)

    container.resolve(Box[int])
    container.compile()

    service_key = ServiceKey.from_value(Box[int])
    assert service_key not in container._compiled_providers


def test_compile_skips_scoped_typevar_map_registrations(container: Container) -> None:
    class Box(Generic[T]):
        pass

    service_key = ServiceKey.from_value(Box[int])
    registration = Registration(
        service_key=service_key,
        factory=None,
        instance=None,
        lifetime=Lifetime.SCOPED,
        scope="request",
        is_async=False,
        concrete_type=None,
        typevar_map={T: int},
    )
    container._scoped_registry[(service_key, "request")] = registration
    container.compile()

    assert (service_key, "request") not in container._scoped_compiled_providers


def test_compile_skips_scoped_typevar_dependency(container: Container) -> None:
    class ScopedTypevar(Generic[T]):
        def __init__(self, kind: type[T]) -> None:
            self.kind = kind

    container.register(
        ScopedTypevar,
        lifetime=Lifetime.SCOPED,
        scope="request",
    )
    container.compile()

    service_key = ServiceKey.from_value(ScopedTypevar)
    assert (service_key, "request") not in container._scoped_compiled_providers


def test_typevar_dependency_default_without_typevar_map(container: Container) -> None:
    default_kind: Any = str

    class TypevarDefault(Generic[T]):
        def __init__(self, kind: type[T] = default_kind) -> None:  # type: ignore[assignment]
            self.kind = kind

    container.register(TypevarDefault)

    result = container.resolve(TypevarDefault)
    assert result.kind is str


def test_concrete_generic_alias_as_interface_key(container: Container) -> None:
    """Test registering a class as implementation for a concrete generic alias."""

    @dataclass
    class Box(Generic[T]):
        value: str

    @dataclass
    class ConcreteIntBox:
        value: str = "concrete int box"

    # Register ConcreteIntBox as the implementation for Box[int]
    decorator = cast(
        "Callable[[type], type]",
        container.register(Box[int]),
    )
    decorator(ConcreteIntBox)

    result = container.resolve(Box[int])
    assert isinstance(result, ConcreteIntBox)
    assert result.value == "concrete int box"


def test_concrete_generic_alias_factory_registration(container: Container) -> None:
    """Test registering a factory for a concrete generic alias."""

    @dataclass
    class Box(Generic[T]):
        value: str

    decorator = cast(
        "Callable[[Callable[..., object]], Callable[..., object]]",
        container.register(Box[str]),
    )

    def create_str_box() -> Box[str]:
        return Box(value="custom string box")

    decorator(create_str_box)

    result = container.resolve(Box[str])
    assert result.value == "custom string box"
