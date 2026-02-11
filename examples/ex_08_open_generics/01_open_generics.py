"""Open generics: registration, specificity, overrides, and validation.

This module covers progressively advanced open-generic behavior:

1. Open generic factory registration and type-argument injection.
2. Closed generic override precedence.
3. Most-specific template winner (``Repo[list[U]]`` over ``Repo[T]``).
4. TypeVar bound validation errors.
5. Scoped open-generic resolution requiring a matching opened scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from diwire import Container, Lifetime, Scope
from diwire.exceptions import DIWireInvalidGenericTypeArgumentError, DIWireScopeMismatchError

T = TypeVar("T")
U = TypeVar("U")


class IBox(Generic[T]):
    pass


@dataclass(slots=True)
class Box(IBox[T]):
    type_arg: type[T]


class _SpecialIntBox(IBox[int]):
    pass


def build_box(type_arg: type[T]) -> IBox[T]:
    return Box(type_arg=type_arg)


class Repo(Generic[T]):
    pass


@dataclass(slots=True)
class GenericRepo(Repo[T]):
    dependency_type: type[T]


@dataclass(slots=True)
class ListRepo(Repo[list[U]]):
    item_type: type[U]


class Model:
    pass


class User(Model):
    pass


M = TypeVar("M", bound=Model)


class ModelBox(Generic[M]):
    pass


@dataclass(slots=True)
class DefaultModelBox(ModelBox[M]):
    type_arg: type[M]


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.register_factory(IBox, factory=build_box)

    box_int = cast("Box[int]", container.resolve(IBox[int]))
    print(f"box_int={box_int.type_arg.__name__}")  # => box_int=int

    container.register_concrete(IBox[int], concrete_type=_SpecialIntBox)
    override = container.resolve(IBox[int])
    print(f"override={type(override).__name__}")  # => override=_SpecialIntBox

    container.register_concrete(Repo, concrete_type=GenericRepo)
    container.register_concrete(Repo[list[U]], concrete_type=ListRepo)
    specific_repo = cast("ListRepo[int]", container.resolve(Repo[list[int]]))
    print(f"specificity_item={specific_repo.item_type.__name__}")  # => specificity_item=int

    validation_container = Container(autoregister_concrete_types=False)
    validation_container.register_concrete(ModelBox, concrete_type=DefaultModelBox)
    invalid_key = cast("Any", ModelBox)[str]
    try:
        validation_container.resolve(invalid_key)
    except DIWireInvalidGenericTypeArgumentError as error:
        invalid_generic = type(error).__name__
    print(
        f"invalid_generic={invalid_generic}",
    )  # => invalid_generic=DIWireInvalidGenericTypeArgumentError

    scoped_container = Container(autoregister_concrete_types=False)
    scoped_container.register_factory(
        IBox,
        factory=build_box,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    try:
        scoped_container.resolve(IBox[int])
    except DIWireScopeMismatchError:
        scoped_requires_scope = True
    else:
        scoped_requires_scope = False
    print(f"scoped_requires_scope={scoped_requires_scope}")  # => scoped_requires_scope=True


if __name__ == "__main__":
    main()
