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

### Measurement extension: cold compilation and retained memory

`tests/performance/test_compile_workloads.py` measures fresh compilation with 16,
64 and 256 independent request-scope transient providers. Each of 20 measured
rounds (after three warmups) registers a new container outside timing, compiles it
once with GC enabled, then validates transient resolution and closes it outside
timing. The target returns no resolver to the benchmark framework. Explicit final
cleanup also supports `--benchmark-disable`, which omits framework teardown.

`python -m tests.performance.measure_compile_memory --output UNIQUE_PATH` measures
allocation separately from timings. Registrations precede tracing; peak is read
immediately after compilation, and retained bytes after collection with the root
still live. Introspection happens after tracing stops. It reports shallow globals
mapping bytes, unique namespace count and generated function count in addition to
traced allocation, with full source/harness/configuration fingerprints and runtime
identity. The initial 256-provider probe retained 71.29 MB, including 68.07 MB of
shallow globals-dictionary storage spread across 2,615 generated functions.

Measurement-only validation: three new benchmark cases pass disabled-mode checks;
`make lint` and `make test` pass, 1,115 tests, 77 skips, 100% coverage. The independent
review required canonical-helper/configuration fingerprinting and explicit GIL
metadata for the memory probe; both are included. No compiler change is part of
this checkpoint. Five fresh-process A/A pairs of cold timings and five separate
A/A memory-probe pairs will set H002's thresholds before runtime edits.

### Hypothesis 002: share generated globals within each compilation

Baseline checkpoint: `5442fda`. Five alternating cold-compilation A/A pairs are in
`h002-calibration-timing/`; five separate allocation A/A pairs are in
`h002-calibration-memory/`. Runtime, dependencies, equal-length paths, hash seed and
battery/low-power settings match H001. All memory statistics were byte-for-byte identical at 64 and 256 providers;
16-provider retained bytes varied by 55 bytes (0.0056%), with other metrics identical. Timing headline/paired differences were
-2.52%/-0.14% at 16 providers, -0.28%/+0.62% at 64, and -0.04%/+0.11% at 256;
therefore short compile-time boundary cases require confirmation.

Hypothesis: every generated function copies the same O(N)-size globals dictionary,
retaining O(N squared) metadata across scope classes.
Change: both function-compilation helpers reuse a plain dictionary supplied by the
current compilation; other Mapping inputs retain their snapshot conversion. The
compiler already creates a fresh dictionary for every build. No cross-build cache
or provider/dispatch change is introduced.
Target: PRIMARY retained compilation memory at 64 and 256 providers, expected >80%
reduction. Startup speed is a secondary measurement, not a retrospective substitute.
Risks: cross-container provider/constructor contamination, old active scopes after
recompilation, altered Mapping behavior, global lookup speed and collectible cycles.
Accept: at least 50% retained-memory reduction at BOTH target sizes in every one of
five paired probes, unchanged generated-function counts, all correctness/review
gates, and no confirmed >2% regression in peak/retained memory at any size, cold
compilation time at any size, or the 26 established steady workloads. Trigger five
focused confirmation pairs if either headline or paired median crosses the 2%
boundary; use at most one extra five-pair extension for a real boundary ambiguity.
Claim a startup speed gain only if both headline and paired median exceed 5% with
at least 4/5 wins. Otherwise report it as neutral or as a measured tradeoff.
Reject: isolation/lifecycle/Mapping failure, insufficient primary memory gain,
missing generated functions, confirmed protected loss, or unresolved confirmation.

H002 measured results meet acceptance criteria. Retained bytes fell from 988,479
to 275,207 at 16 providers (-72.16%), 5,417,276 to 852,452 at 64 (-84.26%), and
71,286,557 to 3,237,797 at 256 (-95.46%), improving in all five pairs at every
size. Peak bytes fell 49.40%, 64.74% and 89.19%, respectively. Generated-function
counts remain 215/695/2,615; each compilation now retains one globals dictionary.
Cold-compilation throughput at 64 providers improved 6.48% headline/6.44% paired
median, and at 256 improved 21.57%/21.66%, both 5/5 wins. Median mean compile times
were 36.925 -> 34.678 ms and 162.950 -> 134.040 ms. The 16-provider result
(+0.27%/+0.47%, 3/5) is neutral.

The original 17-workload synchronous geometric mean changed -0.16%, a control
result rather than a claimed runtime gain. Dedicated five-pair confirmations of
the broad-run flags and borderline workloads found synchronous generator scope
lifecycle -0.02%/-0.27%, open-generic transient -1.03%/-0.78%, singleton
+1.05%/-0.27%, and async generator lifecycle -0.83%/-1.41%. These small measured
tradeoffs are within the declared 2% budget. No confirmation extension was used.

All 50 original runs, round-level data, source/runtime fingerprints, raw artifact
hashes and comparisons are archived in `performance-evidence/2026-09-05/h002.json.gz`.
Original logs, power/process snapshots and runner scripts remain in
`benchmark-results/campaign-2026-09-05/`, under `h002-calibration-timing`,
`h002-calibration-memory`, `h002-ab`, `h002-memory-ab`, and `h002-protected-confirm`.
Independent measurement review verified the evidence and supported acceptance;
semantic/lifecycle reviews found no blockers. Tests cover plain-dict sharing,
Mapping snapshots, colliding provider slots across compilations, overlapping old
scopes, and cycle collection. The GC test skips only free-threaded Python 3.13,
whose interpreter immortalizes dynamically created classes after threads start.

Verification: `make lint` passes. `make test` and full suites on Python 3.10 and
free-threaded Python 3.14 each pass 1,123 tests with 77 skips and 100% coverage.
The free-threaded run explicitly reports the GIL disabled. The final
`make test-e2e-fastapi` gate passed all five tests against a clean export of the
exact staged candidate, using the temporary anonymous Docker configuration.
Compose removed its containers and network. H002 is accepted.

### Hypothesis 003: emit generic slot wrappers from source

Baseline checkpoint: `0196cd264fb1256d8f7788936b8b37ba63693a50`, with the full
remote Python 3.10-3.15/free-threaded matrix, integrations and docs green.
The machine changed to AC power with low-power mode 1 before this experiment.
H001/H002 battery timings remain historical evidence, not pooled observations.
Five fresh alternating A/A pairs across all 29 workloads are retained in
`h003-calibration-aa`; five separate allocation A/A pairs in
`h003-calibration-memory`. Cold-compilation headline/paired changes were
-0.50%/-0.50% at 16, +0.40%/+0.66% at 64, and +0.30%/+0.30% at 256 providers.
Steady A/A boundary noise included mixed async -2.00%/-2.09% and async resolution
of sync transients -1.92%/-2.11%; keep bounded confirmations for either-metric
flags. Allocation metrics were identical at 64/256; 16-provider median retained
bytes differed by 55 bytes (0.020%), with raw retained variation up to 110 bytes
and peak variation up to 55 bytes. No observations were removed.

New ignored runner versions derive the active low-power setting, snapshot before
and after each run, reject unknown sources, and stop on within-run or between-run
power transitions. Original runner versions remain alongside their old evidence.
All H003 timing A/A starting snapshots and observed end state were AC/low-power 1;
subsequent runs use the strengthened runner. Harness and target commands are
otherwise unchanged. Docker is stopped before timings.

Profile: three separate 256-provider compiles at the accepted checkpoint spent
0.294 s of 1.124 s instrumented time in `_compile_slot_method`, including 0.100 s
in existing sync specialization. AST location walking across the compiler used
0.690 s. These instrumented values locate cost; they are not benchmark results.
The profile and script are retained as `h003-baseline-profile.*` and
`profile_h003_baseline.py.txt` in the artifact directory.

Hypothesis: generic slot wrappers allocate Python AST objects and walk their
locations despite emitting only a cache precheck and a simple return.
Change: emit the same generic wrapper through the existing source compiler;
leave sync specialization, helper selection, namespace and dispatch unchanged.
Target: cold-compilation throughput at BOTH 64 and 256 providers, expected >5%.
Risks: source location changes can split a fused cached-load instruction on
Python 3.14; protect all warm async caches, cache precedence, coroutine laziness,
dynamic slot replacement, transitive async requirements, locks and cleanup.
Independent compile-only review of nine representative wrappers found matching
arguments, flags, constants, names, stack requirements and globals; executable
bytecode differs only in current-owner cached wrappers and related jump offsets.
Accept: >=5% headline AND paired median throughput gain at BOTH target sizes,
at least 4/5 paired wins each, all correctness/review gates, unchanged generated
function counts, and no confirmed >2% loss in any of the 26 steady workloads,
16-provider compile throughput, or peak/retained memory at any size.
Run five focused compilation pairs first, then five pairs of the 26 steady
workloads and five separate memory pairs. Any protected flag in headline OR
paired median triggers five focused confirmation pairs; permit at most one
additional five-pair extension for genuine boundary ambiguity.
Reject: semantic/API change, insufficient target gain, confirmed protected loss,
or unresolved confirmation. Reverse only the saved experiment patch on rejection.

H003 preliminary results: 64-provider compilation throughput +7.43% headline/
+7.24% paired and 256-provider +6.98%/+7.50%, all 5/5 wins. Retained memory rose
0.26%/0.34%/0.43% at 16/64/256 providers, with peak increases at most 0.10% and
unchanged generated-function counts. Focused tests passed 213 cases and semantic
review found no issues. These are provisional observations, not acceptance.

The steady series was paused during pair 02 after discovering that existing warm
async caches are root-owned: dispatch returns before the changed generic slot
cache prefix, and root slots can also be replaced after warming. Request lifecycle
timings only measured first use. Canonical sync benchmarks use no locking and
therefore compile specialized slots. The existing guards did not measure the
source-location instruction change on a warm generic cache hit.

Reversed only `h003-candidate.patch`, verified the complete source/test diff against
`0196cd2` was empty, and reran 201 focused checkpoint tests successfully. The ledger
is the only retained tracked difference before extending measurement. All 44
original raw artifacts (including the interrupted partial steady run), summaries,
power metadata and the parked candidate patch are retained in
`performance-evidence/2026-09-05/h003-pre-guard.json.gz`; none were selectively
removed. Do not pool these observations with the forthcoming expanded rebaseline.

### Measurement extension: warm request-owned generic caches

Added four cases in `tests/performance/test_cached_scope_workloads.py`: public
request-scoped async resolution of sync/async/suspending providers and synchronous
resolution with a thread-safe registration that uses the generic slot path. One
scope stays open and warm throughout timing. Provider construction counts remain
one through timing and become two in a subsequent scope; identity checks and
scope/loop teardown are outside timing. This measures warmed cache access, not
lock acquisition or contention. Async results use 1,000-operation batches; the
sync case uses one resolution per callback. Normalize from `operations_per_batch`
(default one), not directory or filename.

Independent measurement/lifecycle review confirmed that these cases reach the
previously unmeasured generic cache-hit prefix. Four executable benchmark checks
pass, as do `make lint` and `make test`: 1,123 passed, 81 skipped, 100% coverage.
The final `make test-e2e-fastapi` gate passed all five tests in the exact staged
source export. No runtime optimization is included in this measurement checkpoint;
H003 will resume from it with unchanged thresholds.
