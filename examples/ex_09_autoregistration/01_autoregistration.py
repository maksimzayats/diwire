"""Autoregistration behaviors at resolve-time and registration-time.

This module demonstrates:

1. Resolve-time concrete autoregistration for dependency chains.
2. Registration-time dependency autoregistration via
   ``autoregister_dependencies=True``.
3. Strict mode behavior when ``autoregister_concrete_types=False``.
4. Skipped/special types (``uuid.UUID``) that require explicit registration.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from diwire import Container
from diwire.exceptions import DIWireDependencyNotRegisteredError


class AutoregLeaf:
    pass


@dataclass(slots=True)
class AutoregBranch:
    leaf: AutoregLeaf


@dataclass(slots=True)
class AutoregRoot:
    branch: AutoregBranch


class RegisterDependency:
    pass


@dataclass(slots=True)
class RegisterRoot:
    dependency: RegisterDependency


@dataclass(slots=True)
class StrictRoot:
    dependency: RegisterDependency


@dataclass(slots=True)
class RootWithUuid:
    request_id: uuid.UUID


def main() -> None:
    resolve_container = Container()
    resolved = resolve_container.resolve(AutoregRoot)
    autoregister_chain = isinstance(resolved.branch.leaf, AutoregLeaf)
    print(f"autoregister_chain={autoregister_chain}")  # => autoregister_chain=True

    register_container = Container(autoregister_dependencies=False)
    register_container.register_concrete(
        concrete_type=RegisterRoot,
        autoregister_dependencies=True,
    )
    try:
        resolved_register_root = register_container.resolve(RegisterRoot)
    except DIWireDependencyNotRegisteredError:
        autoregister_deps_on_register = False
    else:
        autoregister_deps_on_register = isinstance(
            resolved_register_root.dependency,
            RegisterDependency,
        )
    print(
        f"autoregister_deps_on_register={autoregister_deps_on_register}",
    )  # => autoregister_deps_on_register=True

    strict_container = Container(autoregister_concrete_types=False)
    try:
        strict_container.resolve(StrictRoot)
    except DIWireDependencyNotRegisteredError as error:
        strict_missing = type(error).__name__
    print(
        f"strict_missing={strict_missing}",
    )  # => strict_missing=DIWireDependencyNotRegisteredError

    uuid_container = Container()
    try:
        uuid_container.resolve(RootWithUuid)
    except DIWireDependencyNotRegisteredError:
        skipped_before_registration = True
    else:
        skipped_before_registration = False

    expected_uuid = uuid.UUID(int=0)
    uuid_container.register_instance(instance=expected_uuid)
    resolved_uuid = uuid_container.resolve(RootWithUuid)
    uuid_skipped_until_registered = (
        skipped_before_registration and resolved_uuid.request_id is expected_uuid
    )
    print(
        f"uuid_skipped_until_registered={uuid_skipped_until_registered}",
    )  # => uuid_skipped_until_registered=True


if __name__ == "__main__":
    main()
