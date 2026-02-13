"""Open-generics constraints deep dive.

This focused script shows constrained ``TypeVar`` behavior with both valid and
invalid resolutions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from diwire import Container
from diwire.exceptions import DIWireInvalidGenericTypeArgumentError

Allowed = TypeVar("Allowed", int, str)


class ConstrainedBox(Generic[Allowed]):
    pass


@dataclass(slots=True)
class ConstrainedBoxImpl(ConstrainedBox[Allowed]):
    type_arg: type[Allowed]


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(ConstrainedBoxImpl, provides=ConstrainedBox)

    valid_int = container.resolve(ConstrainedBox[int])
    valid_str = container.resolve(ConstrainedBox[str])

    if cast("ConstrainedBoxImpl[int]", valid_int).type_arg is not int:
        msg = "Expected int constrained type argument"
        raise TypeError(msg)
    if cast("ConstrainedBoxImpl[str]", valid_str).type_arg is not str:
        msg = "Expected str constrained type argument"
        raise TypeError(msg)

    invalid_key = cast("Any", ConstrainedBox)[float]
    try:
        container.resolve(invalid_key)
    except DIWireInvalidGenericTypeArgumentError:
        return

    msg = "Expected DIWireInvalidGenericTypeArgumentError for constrained TypeVar"
    raise TypeError(msg)


if __name__ == "__main__":
    main()
