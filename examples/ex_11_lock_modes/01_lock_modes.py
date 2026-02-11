"""Lock mode defaults and per-provider overrides.

This module demonstrates lock behavior for cached (singleton) providers:

1. Default ``lock_mode="auto"`` uses thread locks for sync-only graphs.
2. Container-level ``lock_mode=LockMode.NONE`` disables locking.
3. Provider-level ``lock_mode`` can override the container setting.
"""

from __future__ import annotations

import threading
import time

from diwire import Container, Lifetime, LockMode


class DefaultLockService:
    pass


class ContainerLockService:
    pass


class OverrideLockService:
    pass


def _singleton_two_thread_stats(
    *,
    container: Container,
    provides: type[object],
    lock_mode: LockMode | None = None,
) -> tuple[int, bool]:
    calls = 0
    calls_lock = threading.Lock()
    factory_started = threading.Event()
    factory_release = threading.Event()
    results: list[object | None] = [None, None]

    def factory() -> object:
        nonlocal calls
        with calls_lock:
            calls += 1
            factory_started.set()
        factory_release.wait(timeout=2.0)
        return provides()

    if lock_mode is None:
        container.register_factory(
            provides,
            factory=factory,
            lifetime=Lifetime.SINGLETON,
        )
    else:
        container.register_factory(
            provides,
            factory=factory,
            lifetime=Lifetime.SINGLETON,
            lock_mode=lock_mode,
        )

    resolver = container.compile()

    def worker(index: int) -> None:
        results[index] = resolver.resolve(provides)

    thread_0 = threading.Thread(target=worker, args=(0,))
    thread_0.start()

    if not factory_started.wait(timeout=2.0):
        msg = "Factory was not called within timeout."
        raise RuntimeError(msg)

    thread_1 = threading.Thread(target=worker, args=(1,))
    thread_1.start()

    deadline = time.monotonic() + 0.5
    while True:
        with calls_lock:
            current_calls = calls
        if current_calls >= 2 or time.monotonic() >= deadline:
            break
        time.sleep(0.001)

    factory_release.set()

    for thread in (thread_0, thread_1):
        thread.join(timeout=2.0)
        if thread.is_alive():
            msg = "Worker thread did not finish within timeout."
            raise RuntimeError(msg)

    if results[0] is None or results[1] is None:
        msg = "Worker threads did not store resolution results."
        raise RuntimeError(msg)

    with calls_lock:
        total_calls = calls

    shared = results[0] is results[1]
    return total_calls, shared


def main() -> None:
    default_calls, default_shared = _singleton_two_thread_stats(
        container=Container(),
        provides=DefaultLockService,
    )
    print(
        f"default_auto=calls={default_calls} shared={default_shared}",
    )  # => default_auto=calls=1 shared=True

    none_calls, none_shared = _singleton_two_thread_stats(
        container=Container(lock_mode=LockMode.NONE),
        provides=ContainerLockService,
    )
    print(
        f"container_none=calls={none_calls} shared={none_shared}",
    )  # => container_none=calls=2 shared=False

    override_calls, override_shared = _singleton_two_thread_stats(
        container=Container(lock_mode=LockMode.NONE),
        provides=OverrideLockService,
        lock_mode=LockMode.THREAD,
    )
    print(
        f"override_thread=calls={override_calls} shared={override_shared}",
    )  # => override_thread=calls=1 shared=True


if __name__ == "__main__":
    main()
