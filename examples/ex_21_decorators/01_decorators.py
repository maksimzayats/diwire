"""Decorators: the easiest mental model.

Read this file top-to-bottom in three steps:

1. Register a base service (``Greeter`` -> ``SimpleGreeter``).
2. Add decorators; each new call becomes the new outer layer.
3. Re-register the base service; decorators stay in place automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from diwire import Container


class Greeter(Protocol):
    def greet(self, name: str) -> str: ...


class SimpleGreeter:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def greet(self, name: str) -> str:
        return f"{self.prefix} {name}"


class FriendlyGreeter:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def greet(self, name: str) -> str:
        return f"{self.prefix}, {name}!"


@dataclass(slots=True)
class Tracer:
    events: list[str]

    def record(self, event: str) -> None:
        self.events.append(event)


class TracedGreeter:
    def __init__(self, inner: Greeter, tracer: Tracer) -> None:
        self.inner = inner
        self.tracer = tracer

    def greet(self, name: str) -> str:
        self.tracer.record("greet")
        return self.inner.greet(name)


class CountingGreeter:
    def __init__(self, inner: Greeter) -> None:
        self.inner = inner
        self.calls = 0

    def greet(self, name: str) -> str:
        self.calls += 1
        return self.inner.greet(name)


def main() -> None:
    container = Container()
    container.add_instance("Hello", provides=str)
    tracer = Tracer(events=[])
    container.add_instance(tracer, provides=Tracer)
    container.add(SimpleGreeter, provides=Greeter)

    # Step 1: one decorator.
    container.decorate(provides=Greeter, decorator=TracedGreeter)
    traced_greeter = container.resolve(Greeter)
    traced_result = traced_greeter.greet("Sam")
    print(f"step1_outer={type(traced_greeter).__name__}")  # => step1_outer=TracedGreeter
    print(
        f"step1_inner={type(traced_greeter.inner).__name__}",
    )  # => step1_inner=SimpleGreeter
    print(
        f"step1_result={traced_result}",
    )  # => step1_result=Hello Sam
    print(f"step1_events={len(tracer.events)}")  # => step1_events=1

    # Step 2: add another decorator; this one becomes outermost.
    container.decorate(provides=Greeter, decorator=CountingGreeter)
    stacked_greeter = container.resolve(Greeter)
    stacked_result = stacked_greeter.greet("Pat")
    print(f"step2_outer={type(stacked_greeter).__name__}")  # => step2_outer=CountingGreeter
    print(f"step2_inner={type(stacked_greeter.inner).__name__}")  # => step2_inner=TracedGreeter
    print(
        f"step2_base={type(stacked_greeter.inner.inner).__name__}",
    )  # => step2_base=SimpleGreeter
    print(
        f"step2_result={stacked_result}",
    )  # => step2_result=Hello Pat
    print(f"step2_calls={stacked_greeter.calls}")  # => step2_calls=1

    # Step 3: replace the base binding; decorators remain.
    container.add_instance("Hi", provides=str)
    container.add(FriendlyGreeter, provides=Greeter)
    rebound_greeter = container.resolve(Greeter)
    rebound_result = rebound_greeter.greet("Lee")
    print(
        f"step3_base={type(rebound_greeter.inner.inner).__name__}",
    )  # => step3_base=FriendlyGreeter
    print(
        f"step3_result={rebound_result}",
    )  # => step3_result=Hi, Lee!


if __name__ == "__main__":
    main()
