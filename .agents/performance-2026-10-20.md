# Constructor annotation correction, 20 October 2026

## Decision: keep the PR open, do not merge

This is a proven dependency-inference bug fix, with no speedup claim. Semantic review
passes. Measurement review blocks merge because settings registration is slower in
all eight comparisons. The owner's no-regression condition is not established.
Do not repeat identical source runs until a favorable result appears. A follow-up
needs a justified source change, a new declared protocol, and fresh measurements
and reviews. This candidate is retained in an open PR for that work.

## Problem and change

Baseline: `6d867607dcb74f1f045aa6a556163685db4a4c66`.
When a class stores `value: Stored` but its constructor takes `value: Input`, class
field hints previously caused DIWire to inject `Stored`. A container regression
uses an existing `Input` instance and verifies that this exact object reaches the
constructor before it stores a different type. Direct, postponed and quoted
annotations exercise the same failure.

Only private provider inspection changes. It selects the construction callable
from the metaclass or nearest Python `__new__`/`__init__` in the MRO. Decorator
unwrapping stops at explicit method signatures. Resolved constructor hints take
priority over class fields for normal classes. Synthetic signatures retain field
hints as fallback. Fully resolved signature annotations take priority; recursive
checks preserve resolved forward hints, `Annotated` metadata, `Literal` values,
Callable arguments and NoneType. Dataclass, attrs converter, NamedTuple, msgspec,
Pydantic, inheritance and decorator cases are covered. No public signature or
runtime resolver changes.

The baseline fails 13 cases in the final focused test file; the candidate passes
50, with one expected Pydantic 1 skip on Python 3.14. Independent semantic review
also passes 15 probes. Existing all-or-nothing `get_type_hints` limitations remain
for unresolved string parameters plus unrelated invalid return hints. This change
does not add a new forward-reference resolver.

## Reproducible regression guard

CPython 3.14.7, GIL build, Apple M1 Pro, macOS 27.0.1 arm64. Same checkout,
interpreter, dependencies, lock and benchmark harness for both source roles.
The source alone changes between fresh processes and is restored afterwards.
AC power, 80% battery. The initial process snapshot includes system work up to
31.6% CPU. Per-run power, frequency, temperature and affinity were not recorded.
These conditions limit timing precision.

Protocol was saved before source edits. Three baseline registration runs establish
spread. Three alternating broad pairs cover 17 canonical resolution workloads,
three cold-compile sizes and two recursive registration cases. Every cell with
median throughput below -2% receives five alternating focused pairs. The declared
confirmation tolerance is max(2%, baseline spread where measured). All samples,
outliers and failed preparation gates are retained.

Commands, run names and parameters are in archived `experiment.py` and per-run
`*.context.json`. For example:

```sh
uv run --no-sync python -m pytest tests/performance/test_registration_workloads.py \
  -k benchmark_diwire --benchmark-only --benchmark-columns=mean,stddev -q \
  --benchmark-json=<unique-path>.json
```

The existing registration harness uses 20 rounds, three warmup rounds, one
iteration and GC enabled. Container/type setup, compile and teardown are outside
registration timing. Cold compile excludes registration. No harness changes.
Baseline cProfile confirms class dependency inspection occurs in registration;
profile times are not used as benchmark effects.

Final baseline spread: plain 3.5605%, settings 9.0365%. The earlier dev-only
preflight calibration is retained separately and is not used for the decision.
After docs dependencies were restored with `uv sync --all-groups`, final
calibration, broad and confirmation runs use one stable environment.

| Confirmed cell | Broad throughput | Five-pair confirmation throughput |
| --- | ---: | ---: |
| Scoped open/closed generics | -2.3785% | -0.9117% |
| Wide transient graph | -4.2738% | -0.6144% |
| Cold compile, 64 providers | -3.0161% | +0.4121% |
| Plain recursive registration | -3.9673% | -0.6128% |
| Settings recursive registration | -4.7168% | -4.4649% |

The formal max(noise, 2%) rule passes. That does not establish safe performance:
settings loses all three broad and all five confirmation pairs. Confirmation
means imply 4.6736% more time. Diagnostic round-median comparisons also lose all
eight pairs; this was not a new acceptance rule. Settings calibration CV is
6.18-14.96%, confirmation CV is 6.25-12.48%, and one broad candidate CV is 53.78%.
Baseline spread is not a confidence interval for the paired effect. Independent
measurement review therefore blocks merge despite the formal rule result.

The independent audit recomputes 19 final process artifacts, 188 cell means and
1,930 rounds, checks the exact five-cell confirmation set and all source, lock,
harness and role-tree hashes. There is no general application performance claim.

## Quality and evidence

- `make lint`: Ruff, formatting and strict mypy pass.
- `make test`: 1,209 passed, 99 skipped, 100% statement and branch coverage.
- Public API golden file is unchanged.
- `make test-e2e-fastapi`: five tests pass; containers and network are removed.
- CI and exact committed-head review are separate PR checks. Neither removes
  the measurement blocker.

Source SHA256: `09ae323017ae427fb2489e72ad03f5ee4b5c18fce336983aab65d430f5d8fd3d`.
Lock SHA256: `1a7d9607319f28a607189605a9af0626f97dab646ef2d52c6c553c9889b53311`.
Compressed evidence: `.agents/performance-evidence/2026-10-20/constructor-annotations.json.gz`.
Raw local evidence: `/Users/mac/os/.local/diwire/runs/2026-10-20-constructor-annotations/`.

Archive SHA256: `c6e861dffa959b59ca60a9d24ce9c437ea4534f5d4287032f571fdc51a92a048`. The archive contains 104 text entries.

CI follow-up: the first PR head used a direct Pydantic import in the new field
regression test. Python 3.15 and Python 3.15t CI omit that optional dependency,
so the test must use the existing importorskip convention. The follow-up changes
only this test guard and this note. Runtime source, dependency lock and all
benchmark files remain byte-identical to the measured candidate. It does not
remove or change the settings performance blocker. The archive preserves the
original head's test and gate receipts; later CI receipts remain in local state.
