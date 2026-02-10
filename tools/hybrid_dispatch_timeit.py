from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import timeit
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """A single benchmark row comparing legacy and hybrid dispatch timings."""

    name: str
    before_ns_op: float
    after_ns_op: float
    ratio_after_over_before: float
    before_behavior: str
    after_behavior: str


def _compile_identity_dispatch(keys: tuple[Any, ...]) -> Any:
    lines = ["def resolve(dependency):"]
    for index in range(len(keys)):
        lines.append(f"    if dependency is _dep_{index}:")
        lines.append(f"        return {index}")
    lines.append("    raise KeyError(dependency)")
    source = "\n".join(lines)
    namespace: dict[str, Any] = {f"_dep_{index}": key for index, key in enumerate(keys)}
    exec(source, namespace)  # noqa: S102
    return namespace["resolve"]


def _compile_hybrid_dispatch(
    *,
    identity_keys: tuple[Any, ...],
    equality_keys: tuple[Any, ...],
) -> Any:
    equality_slot_by_key = {
        key: len(identity_keys) + index for index, key in enumerate(equality_keys)
    }
    lines = ["def resolve(dependency):"]
    for index in range(len(identity_keys)):
        lines.append(f"    if dependency is _dep_{index}:")
        lines.append(f"        return {index}")
    if equality_slot_by_key:
        lines.extend(
            [
                "    slot = _dep_eq_slot_by_key.get(dependency, _missing_slot)",
                "    if slot is not _missing_slot:",
                "        return slot",
            ],
        )
    lines.append("    raise KeyError(dependency)")
    source = "\n".join(lines)
    namespace: dict[str, Any] = {
        **{f"_dep_{index}": key for index, key in enumerate(identity_keys)},
        "_dep_eq_slot_by_key": equality_slot_by_key,
        "_missing_slot": object(),
    }
    exec(source, namespace)  # noqa: S102
    return namespace["resolve"]


def _measure_pair_ns_per_op(
    *,
    before_callable: Any,
    after_callable: Any,
    number: int,
    repeat: int,
) -> tuple[float, float]:
    before_timer = timeit.Timer(before_callable)
    after_timer = timeit.Timer(after_callable)
    before_callable()
    after_callable()

    before_runs = [before_timer.timeit(number=number) for _ in range(repeat)]
    after_runs = [after_timer.timeit(number=number) for _ in range(repeat)]
    before_ns = (statistics.median(before_runs) * 1_000_000_000.0) / number
    after_ns = (statistics.median(after_runs) * 1_000_000_000.0) / number
    return before_ns, after_ns


def _class_keys(count: int) -> tuple[type[Any], ...]:
    return tuple(type(f"_DispatchBenchClass{index}", (), {}) for index in range(count))


def _scenario_class_path(
    *,
    provider_count: int,
    position_name: str,
    index: int,
    number: int,
    repeat: int,
) -> ScenarioResult:
    keys = _class_keys(provider_count)
    dependency = keys[index]
    before_dispatch = _compile_identity_dispatch(keys)
    after_dispatch = _compile_hybrid_dispatch(identity_keys=keys, equality_keys=())

    def before_call() -> None:
        _ = before_dispatch(dependency)

    def after_call() -> None:
        _ = after_dispatch(dependency)

    before_ns, after_ns = _measure_pair_ns_per_op(
        before_callable=before_call,
        after_callable=after_call,
        number=number,
        repeat=repeat,
    )
    return ScenarioResult(
        name=f"class_{position_name}_n{provider_count}",
        before_ns_op=before_ns,
        after_ns_op=after_ns,
        ratio_after_over_before=after_ns / before_ns,
        before_behavior="hit",
        after_behavior="hit",
    )


def _scenario_alias_equal_not_identical(
    *,
    alias_name: str,
    alias_factory: Any,
    number: int,
    repeat: int,
) -> ScenarioResult:
    class_keys = _class_keys(32)
    registration_alias = alias_factory()
    lookup_alias = alias_factory()
    if lookup_alias is registration_alias or lookup_alias != registration_alias:
        msg = f"Expected equal but non-identical alias key for {alias_name}."
        raise RuntimeError(msg)

    before_dispatch = _compile_identity_dispatch((*class_keys, registration_alias))
    after_dispatch = _compile_hybrid_dispatch(
        identity_keys=class_keys,
        equality_keys=(registration_alias,),
    )

    def before_call() -> None:
        try:
            before_dispatch(lookup_alias)
        except KeyError:
            return
        msg = "Legacy identity dispatch unexpectedly resolved an equal non-identical alias."
        raise RuntimeError(msg)

    def after_call() -> None:
        _ = after_dispatch(lookup_alias)

    before_ns, after_ns = _measure_pair_ns_per_op(
        before_callable=before_call,
        after_callable=after_call,
        number=number,
        repeat=repeat,
    )
    return ScenarioResult(
        name=f"alias_equal_not_identical_{alias_name}",
        before_ns_op=before_ns,
        after_ns_op=after_ns,
        ratio_after_over_before=after_ns / before_ns,
        before_behavior="miss",
        after_behavior="hit",
    )


def _scenario_unknown_miss(*, number: int, repeat: int) -> ScenarioResult:
    class_keys = _class_keys(64)
    alias_key = list[int]
    unknown_dependency = object()

    before_dispatch = _compile_identity_dispatch((*class_keys, alias_key))
    after_dispatch = _compile_hybrid_dispatch(
        identity_keys=class_keys,
        equality_keys=(alias_key,),
    )

    def before_call() -> None:
        try:
            before_dispatch(unknown_dependency)
        except KeyError:
            return
        msg = "Unknown dependency unexpectedly resolved in identity dispatch."
        raise RuntimeError(msg)

    def after_call() -> None:
        try:
            after_dispatch(unknown_dependency)
        except KeyError:
            return
        msg = "Unknown dependency unexpectedly resolved in hybrid dispatch."
        raise RuntimeError(msg)

    before_ns, after_ns = _measure_pair_ns_per_op(
        before_callable=before_call,
        after_callable=after_call,
        number=number,
        repeat=repeat,
    )
    return ScenarioResult(
        name="unknown_miss_mixed_n65",
        before_ns_op=before_ns,
        after_ns_op=after_ns,
        ratio_after_over_before=after_ns / before_ns,
        before_behavior="miss",
        after_behavior="miss",
    )


def _collect_results(*, number: int, repeat: int) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for provider_count in (8, 32, 128):
        indices = {
            "first": 0,
            "middle": provider_count // 2,
            "last": provider_count - 1,
        }
        for position_name, index in indices.items():
            results.append(
                _scenario_class_path(
                    provider_count=provider_count,
                    position_name=position_name,
                    index=index,
                    number=number,
                    repeat=repeat,
                ),
            )

    alias_factories = {
        "list_int": lambda: list[int],
        "dict_str_int": lambda: dict[str, int],
        "tuple_int_var": lambda: tuple[int, ...],
        "int_or_str": lambda: int | str,
    }
    for alias_name, alias_factory in alias_factories.items():
        results.append(
            _scenario_alias_equal_not_identical(
                alias_name=alias_name,
                alias_factory=alias_factory,
                number=number,
                repeat=repeat,
            ),
        )

    results.append(_scenario_unknown_miss(number=number, repeat=repeat))
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--number",
        type=int,
        default=200_000,
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=7,
    )
    args = parser.parse_args()

    results = _collect_results(number=args.number, repeat=args.repeat)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "number": args.number,
        "repeat": args.repeat,
        "results": [asdict(result) for result in results],
        "command": " ".join([*sys.argv]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
