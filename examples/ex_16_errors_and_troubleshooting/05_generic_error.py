"""Focused example: ``DIWireInvalidGenericTypeArgumentError``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from diwire import Container
from diwire.exceptions import DIWireInvalidGenericTypeArgumentError


class Model:
    pass


M = TypeVar("M", bound=Model)


class ModelBox(Generic[M]):
    pass


@dataclass(slots=True)
class DefaultModelBox(ModelBox[M]):
    type_arg: type[M]


def main() -> None:
    container = Container()
    container.add_concrete(DefaultModelBox, provides=ModelBox)

    invalid_key = cast("Any", ModelBox)[str]
    try:
        container.resolve(invalid_key)
    except DIWireInvalidGenericTypeArgumentError as error:
        error_name = type(error).__name__

    print(f"generic={error_name}")  # => generic=DIWireInvalidGenericTypeArgumentError


if __name__ == "__main__":
    main()
