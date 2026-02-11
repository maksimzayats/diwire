"""Supported framework constructors/fields for dependency extraction.

This module demonstrates constructor/field extraction for:

1. ``dataclasses``
2. ``NamedTuple``
3. ``attrs.define``
4. ``pydantic.BaseModel`` (v2)
5. ``msgspec.Struct``

A single shared dependency instance is registered and each framework-backed
consumer resolves it through explicit concrete registrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import attrs
import msgspec
import pydantic

from diwire import Container


@dataclass(slots=True)
class FrameworkDependency:
    name: str


@dataclass(slots=True)
class DataclassConsumer:
    dependency: FrameworkDependency


class NamedTupleConsumer(NamedTuple):
    dependency: FrameworkDependency


@attrs.define
class AttrsConsumer:
    dependency: FrameworkDependency


class PydanticConsumer(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    dependency: FrameworkDependency


class MsgspecConsumer(msgspec.Struct):
    dependency: FrameworkDependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    dependency = FrameworkDependency(name="framework")
    container.add_instance(dependency)

    container.add_concrete(DataclassConsumer)
    container.add_concrete(NamedTupleConsumer)
    container.add_concrete(AttrsConsumer)
    container.add_concrete(PydanticConsumer)
    container.add_concrete(MsgspecConsumer)

    dataclass_ok = container.resolve(DataclassConsumer).dependency is dependency
    namedtuple_ok = container.resolve(NamedTupleConsumer).dependency is dependency
    attrs_ok = container.resolve(AttrsConsumer).dependency is dependency
    pydantic_ok = container.resolve(PydanticConsumer).dependency is dependency
    msgspec_ok = container.resolve(MsgspecConsumer).dependency is dependency

    print(f"dataclass_ok={dataclass_ok}")  # => dataclass_ok=True
    print(f"namedtuple_ok={namedtuple_ok}")  # => namedtuple_ok=True
    print(f"attrs_ok={attrs_ok}")  # => attrs_ok=True
    print(f"pydantic_ok={pydantic_ok}")  # => pydantic_ok=True
    print(f"msgspec_ok={msgspec_ok}")  # => msgspec_ok=True


if __name__ == "__main__":
    main()
