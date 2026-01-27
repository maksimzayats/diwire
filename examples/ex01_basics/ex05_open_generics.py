from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from diwire import Container


class Model:
    pass


class User(Model):
    pass


T = TypeVar("T")
M = TypeVar("M", bound=Model)


@dataclass
class AnyBox(Generic[T]):
    value: str


@dataclass
class ModelBox(Generic[M]):
    model: M


@dataclass
class NonGenericModelBox:
    value: str


container = Container()


# Use TYPE_CHECKING guard to satisfy pyrefly while using TypeVars at runtime
if TYPE_CHECKING:
    any_box_key: Any = AnyBox[Any]
    model_box_key: Any = ModelBox[Any]
else:
    any_box_key = AnyBox[T]
    model_box_key = ModelBox[M]


@cast("Any", container.register(any_box_key))
def create_any_box(type_arg: type[T]) -> AnyBox[T]:
    return AnyBox(value=type_arg.__name__)


@cast("Any", container.register(model_box_key))
def create_model_box(model_cls: type[M]) -> ModelBox[M]:
    return ModelBox(model=model_cls())


@cast("Any", container.register(NonGenericModelBox))
def create_non_generic_model_box() -> NonGenericModelBox:
    return NonGenericModelBox(value="non-generic box")


@cast("Any", container.register(AnyBox[float]))
@cast("Any", container.register("LazyStringKey"))
@dataclass
class NonGenericModelBox2:
    value: str = "non-generic box 2"


print(container.resolve(AnyBox[int]))
print(container.resolve(AnyBox[str]))
print(container.resolve(AnyBox[float]))  # should use NonGenericModelBox2
print(container.resolve("LazyStringKey"))  # should use NonGenericModelBox2
print(container.resolve(ModelBox[User]))
print(container.resolve(NonGenericModelBox))
print(container.resolve(NonGenericModelBox2))
