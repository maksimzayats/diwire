# Performance campaign: 2026-09-05

## Contract

Improve representative DIWire workloads while preserving public API, correctness,
thread safety, async behavior, cleanup, startup and memory behavior. The campaign
continues until the user stops it. After three unsuccessful well-founded hypotheses
in one area, pivot to another workload or profile again; do not lower acceptance
standards to force a commit.

One writer owns implementation. Independent agents review hypotheses, semantics and
measurement. Each accepted runtime change is a separate Conventional Commit.
Rejected candidates are reversed before the next experiment, with evidence retained.

## Baseline and isolation

- Baseline: `5b73a0d90b0f22e3d7004f08456f2b2ab8b5ac2a`.
- Branch: `codex/perf-2026-09-05`.
- Equal-length sibling worktrees: `diwire-perf-base` and `diwire-perf-work`.
- Original checkout and its pre-existing untracked `diwire/` are untouched.
- CPython 3.14.6, Apple M3 Pro, 12 CPUs, 36 GiB RAM, macOS 26.5.2 (25F84).
- Initial power: battery, low-power mode off. Record power before timing runs;
  retain noisy runs and rebaseline if power mode changes.
- `uv.lock` SHA-256:
  `e47db193cf305a0b72851e7b57fa4d908d1ba427c5964b75715233f0ee60f136`.
- Suite SHA-256:
  `3b4dca8d0e66998e421a175dfc5cedf8b4b3d8b12dd18146333f2edb57c09f24`.
- Dependencies: `uv sync --locked --group dev --group docs` in each worktree.
- Use `UV_NO_SYNC=1` for quality gates to preserve the docs test dependencies.
- Raw artifacts live in the candidate worktree's ignored
  `benchmark-results/campaign-2026-09-05/`, with unique paths per run.

## Measurement protocol

Start with repeated fresh-process unchanged-baseline runs to measure current noise.
Predeclare each hypothesis and its target, practical effect threshold, regression
tolerance and rejection rule before editing runtime code. Derive thresholds from
current noise; the prior campaign's 3% effect and 2% regression boundaries are
reference points, not evidence for today's environment.

Use the existing pytest-benchmark lifecycle boundaries, 3 warmup rounds, 5 measured
rounds and workload-specific iteration counts. Retain raw round data with
`--benchmark-save-data`. Alternate baseline/candidate order in at least five fresh
process pairs for decision-grade confirmation. Headline throughput is the median
of independent-run mean throughput. Require a useful effect and at least four
paired wins; inspect all 17 protected scenarios and confirm suspected regressions
with focused pairs. Profile separately from official timings. Do not run checks,
profilers or CPU-heavy agents concurrently with official timings.

Canonical subject command (unique artifact path for every run):

```sh
uv run --no-sync pytest tests/benchmarks -k benchmark_diwire --benchmark-only \
  --benchmark-save-data --benchmark-json=ABSOLUTE_UNIQUE_PATH -q
```

## Verification

Each accepted candidate must pass formatting, `make lint`, `make test` with 100%
branch/statement coverage and the unchanged API snapshot. Verify minimum Python
and free-threaded Python for runtime changes; use the CI matrix for broader
platform/runtime checks. Run `make test-e2e-fastapi` as the last verification step.

## Experiments

No runtime candidate measured yet. This initial commit establishes the reviewable
campaign and draft PR; it makes no performance claim.

### Measurement extension

Added `tests/performance/test_aresolve_workloads.py` outside the frozen canonical
suite. Nine cases exercise synchronous, coroutine-only and suspending providers,
warm caches, a mixed graph, and class/generator scope lifecycles through the async
API. Each measured batch performs 1,000 public operations, with 100 batches per
round, 3 warmup rounds and 5 measured rounds. Event-loop creation/shutdown and
identity assertions are outside timing; lifecycle entry and cleanup remain inside
each operation, and generator counts are verified. Raw rates are batches/second;
per-operation rates multiply by 1,000. These rates are never mixed into the original
17-scenario throughput aggregate.

Validation: nine benchmark cases pass with `--benchmark-disable`; `make lint` and
`make test` pass (1,108 tests, 74 skips, 100% coverage). Raw benchmark JSON already
retains timing samples; no separate pytest saved-data archive is required.

### Calibration and hypothesis 001: direct async-to-sync slot delegation

Calibration: `run_pairs.py calibration-aa --pairs 5 --suite all`, ten unique raw
files under `benchmark-results/campaign-2026-09-05/calibration-aa/`. Both roles ran
commit `8edcaaf`, CPython 3.14.6 with GIL, identical locked dependency versions,
`PYTHONHASHSEED=0`, battery power with low-power mode off. Source, harness, machine,
commands, power state and competing-process snapshots are retained per run.

The unchanged-code 17-scenario geometric mean differed by +0.045%. All 26 headline
median shifts were within 1.81%. Individual process outliers reached 28%; none was
excluded. Async transient synchronous-provider calibration had +1.39% headline,
+0.78% paired median and one +15.4% outlier (other pairs -0.4% to +1.4%). A separately
profiled 200,000-operation run attributed 0.065s self-time to the generic async slot
helper and 0.013s to its dynamic lookup, against 0.179s total profiled runtime.

Hypothesis: synchronous workflows reached through aresolve pay for a redundant
helper coroutine, runtime metadata reads, formatted method name and getattr.
Change: generate a dynamic `self.resolve_N()` call directly in the async slot only
when `requires_async` is false; retain its coroutine wrapper and cached precheck.
Target: async transient synchronous-provider batch throughput, expected >10% gain.
Risks: dynamic sync-slot replacement, cold/warm cache behavior, inherited scope
ownership, locks, generator cleanup and transitive async dependencies.
Accept: target headline and paired median improve at least 5%, with at least 4/5
paired wins; all correctness gates and independent reviews pass. The 5% floor is
above typical current noise. All 17 canonical and nine async cases are protected;
a >2% decline in either headline or paired median triggers five focused confirmation
pairs. Discrepant/noisy evidence is inconclusive, requiring further normalization or
more pairs; confirmed >2% regressions reject the candidate.
Reject: semantic change, target below the useful-effect floor, insufficient paired
wins, or a confirmed protected regression. Reverse only the recorded experiment
patch and verify the checkpoint tree/index before the next hypothesis.

Independent calibration review verified every raw cell, round, fingerprint and
summary. Protected confirmations trigger on either metric; permit only one
additional five-pair extension for an inconclusive confirmation, then classify
unresolved evidence as inconclusive and reject/pivot. Do not repeatedly extend
until a favorable result appears. Runs include normal desktop background activity;
a power-source transition invalidates pooling across configurations.

H001 accepted: target throughput improved 2.830M to 6.259M
operations/s (+121.18%; paired median +121.28%; 5/5 wins). Async class-scope
lifecycle improved +61.40%; synchronous generator cleanup through the async API
improved +19.96%, both 5/5. The original 17-scenario geometric mean changed +0.57%;
this is a control summary, not a claimed synchronous runtime optimization.

Four protected flags required confirmation. Deep chain changed -2.95%/-2.19%
(headline/paired median) in the broad run, then +0.69%/+0.62% across ten dedicated
pairs. Mixed async changed -2.22%/-2.64% broadly, then -1.12%/-0.94% across ten
pairs. Its first five dedicated pairs were near the boundary, so the one
predeclared extension was used. Singleton changed -2.11%/-1.52% broadly, then
+1.16%/+1.26% across five dedicated pairs. Warm async cache changed -2.20%/-0.39%
broadly, then +0.67%/+0.75% across ten dedicated pairs. Other dedicated warm-cache
controls remained within 1.15% in both metrics. No confirmed loss exceeds 2%.
The mixed-async result is a small measured tradeoff within the declared budget.

Full round-level evidence for all 50 original runs, source/environment fingerprints,
raw artifact SHA-256 values and every workload comparison is committed in
`performance-evidence/2026-09-05/h001.json.gz`. The original JSON files, per-run process
and power snapshots, profiler output and exact runner scripts remain in the ignored
artifact directory. No run or round was removed. Confirmation extension samples
are numbered 06-10 and retain the same command/order as pairs 01-05.

Verification: `make lint` passes; `make test` passes 1,115 tests with 74 skips and
100% statement/branch coverage. The full suite also passes 1,115 tests and 100%
coverage on Python 3.10.19 and free-threaded Python 3.14.6. Focused assembly,
concurrency, API and executable benchmark validation passed 264 tests. Independent
semantic review found no issues with cache precedence, dynamic lookup, coroutine
laziness, transitive async dependencies, locks, cleanup or scopes. Measurement
review validated the raw statistics and required the bounded confirmation step.

Final gate: `make test-e2e-fastapi` passed in a clean export of the exact staged
candidate. The initial attempt timed out resolving the public base image while
the Docker credential helper stalled. A retry with a temporary anonymous Docker
configuration passed; saved Docker settings were untouched. Compose removed its
containers and network afterward.
