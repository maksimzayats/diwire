from dataclasses import dataclass
from typing import Generic, TypeVar

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


@container.register(AnyBox[T])
def create_any_box(type_arg: type[T]) -> AnyBox[T]:
    return AnyBox(value=type_arg.__name__)


@container.register(ModelBox[M])
def create_model_box(model_cls: type[M]) -> ModelBox[M]:
    return ModelBox(model=model_cls())


@container.register(NonGenericModelBox)
def create_non_generic_model_box() -> NonGenericModelBox:
    return NonGenericModelBox(value="non-generic box")


@container.register(AnyBox[float])
@dataclass
class NonGenericModelBox2:
    value: str = "non-generic box 2"


print(container.resolve(AnyBox[int]))
print(container.resolve(AnyBox[str]))
print(container.resolve(AnyBox[float]))  # should use NonGenericModelBox2
print(container.resolve(ModelBox[User]))
print(container.resolve(NonGenericModelBox))
print(container.resolve(NonGenericModelBox2))
