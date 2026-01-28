"""Injected Wrapper Behavior.

Demonstrates:
- Fresh dependency resolution on each call
- Signature transformation (injected params removed)
- Ability to override injected dependencies with kwargs
"""

from dataclasses import dataclass, field
from typing import Annotated

from diwire import Container, Injected, Lifetime


@dataclass
class Counter:
    """A transient counter that tracks its instance number."""

    _counter: int = field(default=0, init=False, repr=False)
    instance_number: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        Counter._counter += 1
        self.instance_number = Counter._counter


def process_item(
    counter: Annotated[Counter, Injected()],
    item_id: int,
) -> str:
    """Process an item, using a counter service."""
    return f"Processing item {item_id} with counter instance #{counter.instance_number}"


def main() -> None:
    container = Container()
    container.register(Counter, lifetime=Lifetime.TRANSIENT)

    injected_func = container.resolve(process_item)

    # 1. Fresh resolution on each call
    print("Fresh resolution on each call:")
    for i in range(1, 4):
        result = injected_func(item_id=i)
        print(f"  {result}")

    # 2. Signature transformation
    print(f"\nOriginal signature: {process_item.__code__.co_varnames[:2]}")
    print(f"Injected signature: {injected_func.__signature__}")
    print("  (Note: 'counter' parameter is removed from signature)")

    # 3. Override injected dependency with explicit kwarg
    print("\nOverriding injected dependency:")
    custom_counter = Counter()
    custom_counter.instance_number = 999
    result = injected_func(item_id=100, counter=custom_counter)
    print(f"  {result}")


if __name__ == "__main__":
    main()
