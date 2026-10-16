# Generic factory keyword arguments, 16 October 2026

Warmed public resolution of generic factories with a runtime dependency takes
11.7% and 12.6% less time in the two tested forms on this CPython 3.14.7 machine.
This result applies to this path and environment. It is not a whole-library,
startup, memory, concurrency, or cross-runtime performance claim.

## Hypothesis and bounded change

`Container._build_materialized_provider_wrapper` copies the call's `kwargs`
before filling injected arguments. Python already creates a fresh dictionary
for the wrapper's `**kwargs` parameter. Fill that dictionary directly with the
same `setdefault` calls. Keep captured defaults, explicit value precedence,
provider call order, return values, exceptions and coroutine handling unchanged.

The profiler attributed 0.952 seconds of internal time to 1,600,004 wrapper calls.
That instrumented result selected the target. It was not used for the speed claim.

## Protocol

Baseline runtime: `e4c27538ea38b4343624b985edc1d401c6f85642`.
Measurement checkpoint: `60ece85` adds a lint-only import fix and tests.
The source baseline and candidate hashes are in the archive. The retained
candidate `container.py` SHA-256 is
`3df48dd3b22195a74e34a7d2c37f4141db3bd7b1cf2f9b1f4a814709c41728e9`.

Environment: macOS arm64, CPython 3.14.7, AC power, same checkout path and
interpreter for both roles. The uv.lock SHA-256 is
`133dd8f6469906bb84d26a89e2ff5ac3e8f92d69d41c61ee83930ebe021dce48`.
Raw JSON includes machine and package metadata. Temperature, CPU frequency and
competing-process state were not captured. Measurements were sequential, with
no concurrent lint, test or benchmark process started by this task.

The new benchmark calls `container.resolve(Repo[int])` with locking and resolver
context disabled. `Repo` has a shared runtime dependency and an injected type
argument. Both positional-or-keyword and keyword-only type arguments are tested.
Materialization, compilation and cleanup are outside the timed region. Assertions
verify the affected wrapper, transient identity, shared identity and closed types.

Each fresh process runs three warmup rounds and five measured rounds of 100,000
operations. Five baseline/candidate pairs alternate order. The controller changes
only the exact owned wrapper patch, then restores the original bytes in `finally`.
Every run has a unique raw path; no samples were removed or overwritten.

Predeclared decision: at least 3% median target time reduction, at least four of
five positive pairs, a useful effect above observed noise, and five focused pairs
to confirm any canonical throughput loss beyond 2%. Stop after one failed candidate.

## Results

| Public generic factory | Calibration range | Median time reduction | Median throughput gain | Positive pairs |
| --- | ---: | ---: | ---: | ---: |
| Positional-or-keyword type | 1.319% | 11.712% | 13.266% | 5/5 |
| Keyword-only type | 8.729% | 12.625% | 14.449% | 5/5 |

The minimum paired target time reductions were 9.807% and 11.825%. All target
pairs had the same direction. The second calibration is noisy, but its range is
smaller than every observed paired target effect. Keep the exact-size estimate
limited to this machine and workload.

Three alternating pairs covered all 17 canonical DIWire scenarios. One scenario,
plain transient resolution, crossed the confirmation boundary at -2.752%
throughput. Five focused confirmation pairs gave -0.248%, -0.883%, +3.755%,
+5.171% and -2.569%, with median -0.248%. The original loss did not reproduce
under the declared median rule. All samples, including a slow candidate round,
remain in the archive. Other broad median losses remained within 2%.
These results do not prove that no regression is possible.

## Correctness and review

Tests cover sync and async factories, public resolution, transient identity,
multiple closed types, caller dictionary isolation, injected defaults, explicit
overrides and later calls. Public API signatures are unchanged.

Independent semantic review found no correctness or concurrency problem.
Independent measurement review verified raw means, arithmetic, public reachability,
equivalent boundaries, confirmation results and the limits of the claim.

`make lint` passed (293 formatted files, 188 typed source files). `make test`
passed 1,172 tests with 95 skips and 100% statement/branch coverage (4,101
statements, 1,516 branches). Public API signature tests passed. The final
implementation check, `make test-e2e-fastapi`, passed all five tests on Docker
CPython 3.14.2 and removed its containers and network. The separate
`datetime as dt` import change repairs Ruff 0.17's pre-existing ICN001 failure
without changing ignored base types. No lint rule was disabled.

## Evidence and reproduction

Archive: `performance-evidence/2026-10-16/materialized-runtime-kwargs.json.gz`.
It contains raw pytest-benchmark JSON, environment, summaries, hashes, the
experiment controller and independent review results. Local working artifacts
and logs are under `/Users/mac/os/.local/diwire/runs/2026-10-16-kwargs/`.

Use the archived controller on the measurement checkpoint with the same test
module and environment. Set its `REPO` and a fresh `OUT` directory first.
Run `calibrate`, then `compare`, `broad` and the protected `confirm` workload.
Each mode refuses to replace an existing raw result. The captured controller
uses the repository interpreter and calls pytest with `--benchmark-only`,
`-k benchmark_diwire` and a unique `--benchmark-json` output for each process.
