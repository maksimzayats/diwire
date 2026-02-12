"""Common error classes for troubleshooting.

This module triggers representative error paths and prints exception type names
so you can recognize each error category quickly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from diwire import (
    Container,
    DIWireAsyncDependencyInSyncContextError,
    DIWireDependencyNotRegisteredError,
    DIWireInvalidGenericTypeArgumentError,
    DIWireInvalidRegistrationError,
    DIWireProviderDependencyInferenceError,
    DIWireScopeMismatchError,
    Scope,
)


class MissingDependency:
    pass


class RequestScopedDependency:
    pass


class AsyncDependency:
    pass


class TypedDependency:
    pass


class Model:
    pass


M = TypeVar("M", bound=Model)


class ModelBox(Generic[M]):
    pass


@dataclass(slots=True)
class DefaultModelBox(ModelBox[M]):
    type_arg: type[M]


def main() -> None:
    missing_container = Container(autoregister_concrete_types=False)
    try:
        missing_container.resolve(MissingDependency)
    except DIWireDependencyNotRegisteredError as error:
        missing = type(error).__name__
    print(f"missing={missing}")  # => missing=DIWireDependencyNotRegisteredError

    scope_container = Container(autoregister_concrete_types=False)
    scope_container.add_concrete(
        RequestScopedDependency,
        provides=RequestScopedDependency,
        scope=Scope.REQUEST,
    )
    try:
        scope_container.resolve(RequestScopedDependency)
    except DIWireScopeMismatchError as error:
        scope = type(error).__name__
    print(f"scope={scope}")  # => scope=DIWireScopeMismatchError

    async_container = Container(autoregister_concrete_types=False)

    async def build_async_dependency() -> AsyncDependency:
        return AsyncDependency()

    async_container.add_factory(build_async_dependency, provides=AsyncDependency)
    try:
        async_container.resolve(AsyncDependency)
    except DIWireAsyncDependencyInSyncContextError as error:
        async_in_sync = type(error).__name__
    print(
        f"async_in_sync={async_in_sync}",
    )  # => async_in_sync=DIWireAsyncDependencyInSyncContextError

    inference_container = Container(autoregister_concrete_types=False)

    def build_typed_dependency(raw_value) -> TypedDependency:  # type: ignore[no-untyped-def]
        _ = raw_value
        return TypedDependency()

    try:
        inference_container.add_factory(build_typed_dependency, provides=TypedDependency)
    except DIWireProviderDependencyInferenceError as error:
        inference = type(error).__name__
    print(f"inference={inference}")  # => inference=DIWireProviderDependencyInferenceError

    generic_container = Container(autoregister_concrete_types=False)
    generic_container.add_concrete(DefaultModelBox, provides=ModelBox)
    invalid_key = cast("Any", ModelBox)[str]
    try:
        generic_container.resolve(invalid_key)
    except DIWireInvalidGenericTypeArgumentError as error:
        generic = type(error).__name__
    print(f"generic={generic}")  # => generic=DIWireInvalidGenericTypeArgumentError

    invalid_registration_container = Container()
    try:
        invalid_registration_container.add_instance(
            provides=cast("Any", None),
            instance=object(),
        )
    except DIWireInvalidRegistrationError as error:
        invalid_reg = type(error).__name__
    print(f"invalid_reg={invalid_reg}")  # => invalid_reg=DIWireInvalidRegistrationError


if __name__ == "__main__":
    main()
