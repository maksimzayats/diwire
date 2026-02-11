"""Focused example: ``uuid.UUID`` requires explicit registration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from diwire import Container
from diwire.exceptions import DIWireDependencyNotRegisteredError


@dataclass(slots=True)
class Root:
    request_id: uuid.UUID


def main() -> None:
    container = Container()

    try:
        container.resolve(Root)
    except DIWireDependencyNotRegisteredError:
        skipped_before_registration = True
    else:
        skipped_before_registration = False

    expected_uuid = uuid.UUID(int=0)
    container.add_instance(expected_uuid)
    resolved = container.resolve(Root)

    print(
        f"uuid_skipped_until_registered={skipped_before_registration and resolved.request_id is expected_uuid}",
    )  # => uuid_skipped_until_registered=True


if __name__ == "__main__":
    main()
