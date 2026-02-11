"""Lock mode defaults and per-provider overrides.

This module demonstrates:

1. Container default lock mode propagation for non-instance registrations.
2. Explicit container-level lock mode configuration.
3. Provider-level ``lock_mode`` override precedence.
"""

from __future__ import annotations

from diwire import Container, LockMode


class DefaultLockService:
    pass


class ContainerLockService:
    pass


class OverrideLockService:
    pass


def main() -> None:
    default_container = Container()
    default_container.register_concrete(concrete_type=DefaultLockService)
    default_lock_mode = default_container._providers_registrations.get_by_type(
        DefaultLockService,
    ).lock_mode
    default_lock_value = (
        default_lock_mode if isinstance(default_lock_mode, str) else default_lock_mode.value
    )
    print(f"default_lock={default_lock_value}")  # => default_lock=auto

    container_lock_none = Container(lock_mode=LockMode.NONE)
    container_lock_none.register_concrete(concrete_type=ContainerLockService)
    container_lock_value = container_lock_none._providers_registrations.get_by_type(
        ContainerLockService,
    ).lock_mode
    print(f"container_lock={container_lock_value.value}")  # => container_lock=none

    container_lock_none.register_factory(
        OverrideLockService,
        factory=OverrideLockService,
        lock_mode=LockMode.THREAD,
    )
    override_lock_value = container_lock_none._providers_registrations.get_by_type(
        OverrideLockService,
    ).lock_mode
    print(f"override_lock={override_lock_value.value}")  # => override_lock=thread


if __name__ == "__main__":
    main()
