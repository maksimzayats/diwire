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

### Measurement adjustment: warm synchronous cache duration

Expanded five-pair A/A at `42aeed8` covered the four new guards and three cold
sizes, with a separate five-pair memory calibration. All 20 raw runs and summaries
are retained in `performance-evidence/2026-09-05/h003-cache-calibration.json.gz`.
Cold headline/paired medians remained within 0.80%; async guards remained within
1.95%. The synchronous warm guard had 2.61%/6.32% baseline/candidate CV and paired
errors up to 9.38% despite identical code. Its measured rounds lasted only
9.2-10.8 ms. The first two slower candidate processes were consistently slower
through all rounds, so this is not merely one removable outlier.

Independent review recommends one measurement-only change: increase that guard
from 100,000 to 1,000,000 iterations, retaining three warmups, five rounds and the
2% regression boundary. Run one fixed five-pair A/A calibration before restoring
the runtime candidate. If comparable instability persists, mark this guard
unresolved and improve conditions or defer H003; do not repeatedly adjust or
sample until a favorable result appears. Do not pool observations from different
harness versions. No runtime change is included in this adjustment.

Validation: `make lint`, four executable benchmark checks, and `make test` pass
(1,123 passed, 81 skipped, 100% coverage). The final `make test-e2e-fastapi` gate
passes all five tests from an exact staged-source export.

### Measurement diagnosis: remove the checkout-role confound

The fixed A/A at `db6b866` (`h003-duration-calibration-aa`) stabilized the longer
synchronous guard: +0.68% headline/+0.14% paired, CV 1.19%/1.55%. However, the warm
suspending-provider guard measured +4.10%/+3.50%, with all five pairs positive.
Its previous expanded A/A was also positive in all five pairs (+1.62%/+1.95%).
Whole rounds differ consistently; these are not removable isolated stalls.
H003 remains unresolved under the two-checkout protocol. This suggests a
role-associated confound, but does not establish checkout layout as the cause.

Independent review supports one fixed diagnostic redesign: use the same checkout
and virtual environment for both fresh-process A/A roles, neutral sequential raw
artifact names, and an external role/order manifest. Retain all workloads,
iterations, warmups, rounds and thresholds. Isolate bytecode caches in one empty
series-wide directory with writes disabled, so later same-path patch transitions
cannot load stale timestamp-based caches. Record this environment explicitly.
Run one five-pair A/A series of the three cold sizes and four warm guards. If ANY
warm guard has headline OR paired bias beyond 2%, defer H003 rather than further
tuning. If it passes, exact-patch transitions between fresh same-path A/B processes
can remove this checkout confound by design; no calibration offset is subtracted.

The fixed same-path A/A (`h003-singlepath-calibration-aa`) passes that rule.
Warm async headline/paired medians are -0.06%/-0.25% (async), -0.49%/-0.34%
(suspending), +0.24%/+0.23% (sync), and -1.76%/-1.30% (THREAD sync). All raw
inputs match pristine `db6b866`; the independent audit verified all metadata,
round counts and manifest entries. Visible stalls remain in the evidence:
run 010 suspending rounds were 258/317/205/160/160 ns per operation (pair effect
-27.58%); run 008 cold-16 included a 32.89 ms round; run 006 cold-64 included
57.33/88.87 ms rounds. No observations were removed, no offset subtracted, and
no calibration extension used. This validates the revised symmetric protocol for
candidate testing; it does not prove checkout identity caused the earlier bias.

H003 resumes from `db6b866` with the exact parked compiler patch. Acceptance
thresholds remain unchanged: >=5% headline AND paired throughput gains at BOTH
64 and 256 providers, >=4/5 wins at each, correctness/review gates, unchanged
generated-function counts, and no confirmed >2% protected regression. Protection
now includes all 30 steady workloads (the original 26 plus four new warm guards),
cold-16, and peak/retained memory at all sizes. Run fresh five-pair same-path A/B
for cold compilation plus the four warm guards first, then separate allocation
and broad steady series. Flagged protections retain the bounded five-pair
confirmation and at most one genuine-boundary five-pair extension.

The runner installs only the exact owned compiler patch before candidate children,
verifies expected source and unchanged other inputs, waits for child completion,
and reverses it after every process and in final cleanup. Neutral artifacts,
manifest mapping, role-specific tree hashes and an empty bytecode cache preserve
the new protocol. No provisional results from previous protocols are pooled.

Candidate focused correctness checks pass 217 tests. Runner validation includes
controlled SIGTERM during a candidate child. An initial check exposed Darwin's
EPERM response when probing an exited process group; process-status checks now
distinguish live members from zombies and verify completion after escalation.
The final interruption check exits 130, leaves both runner/group absent, and
restores an empty diff against HEAD for all source/tests/configuration. Patch
bytes are frozen, staged and unstaged inputs are checked, and unresolved live
child cleanup prevents source reversal until the owner can recover safely.
Interruption-check artifacts are operational validation, not timing evidence.

### H003 result: accept source emission for generic slot wrappers

The fixed five-pair same-path experiment clears both primary thresholds. Cold
compilation at 64 providers improves from 47.270 to 44.345 ms (+6.60% throughput,
+6.90% paired median), and at 256 from 183.191 to 171.082 ms (+7.08%, +6.91%).
Both win all five pairs. Cold-16 improves +5.63%/+5.77% as a secondary result.
The four warmed generic cache guards remain within the regression budget.

Retained traced memory increases by 720/2,880/13,890 bytes at 16/64/256 providers
(+0.26%/+0.34%/+0.43%). Peak changes are -0.65%/-0.06%/+0.10%. Generated function
counts remain 215/695/2,615 and each compilation still has one globals namespace.
These small memory costs are within the declared 2% protection boundary.

The broad 30-workload series has a -0.50% geometric-mean control result for the
original 17 synchronous cases; this is not a runtime speedup claim. Three cases
crossed the headline or paired regression trigger, so the preregistered five-pair
confirmation included them and two borderline controls. Headline/paired effects:

| Protected workload | Initial headline / paired | Confirmation headline / paired |
| --- | --- | --- |
| Sync transient | -1.87% / -2.42% | -0.14% / -0.05% |
| Async class scope lifecycle | -3.26% / -2.50% | +1.05% / +1.72% |
| Warm request async provider | -2.07% / -2.56% | -0.99% / +0.32% |
| Wide transient graph | -1.93% / -1.01% | +0.01% / -0.16% |
| App-scoped async provider | -1.94% / -1.14% | -0.82% / -0.96% |

No confirmation exceeds 2%; no extension or sample exclusion was used. The
largest remaining broad paired loss is 1.62% for async resolution of synchronous
transients. Independent semantic review found no API, cache, locking or cleanup
change, and the independent measurement audit accepts the performance result.

Authoritative commands, run from the candidate checkout at `db6b866`, use
`A=benchmark-results/campaign-2026-09-05` and the archived runner source:

```sh
.venv/bin/python "$A/run_single_path_ab.py.txt" h003-singlepath-focused-ab --patch "$A/h003-candidate.patch"
.venv/bin/python "$A/run_single_path_ab.py.txt" h003-singlepath-memory-ab --kind memory --patch "$A/h003-candidate.patch"
.venv/bin/python "$A/run_single_path_ab.py.txt" h003-singlepath-steady-ab --select 'not cold_compile' --patch "$A/h003-candidate.patch"
.venv/bin/python "$A/run_single_path_ab.py.txt" h003-singlepath-protected-confirm --select 'resolve_transient or resolve_wide_transient_graph or (aresolve_scope_lifecycle and class) or (aresolve_warm_request_cache and async) or (aresolve_provider and SCOPED and async)' --patch "$A/h003-candidate.patch"
```

Environment: CPython 3.14.6 with GIL, M3 Pro (12 CPUs, 36 GiB), macOS 26.5.2,
AC power and low-power mode 1, normal desktop background activity. Locked dev/docs
dependencies, lock SHA-256
`e47db193cf305a0b72851e7b57fa4d908d1ba427c5964b75715233f0ee60f136`.
The same-path protocol uses `PYTHONHASHSEED=0`, one empty series bytecode cache
and `PYTHONDONTWRITEBYTECODE=1`; it is not pooled with earlier protocols or power
states. `performance-evidence/2026-09-05/h003.json.gz` preserves 60 raw runs: ten
diagnostic two-path A/A runs separately labelled, and 50 authoritative same-path
runs (A/A, focused A/B, memory, broad and confirmation). It also includes full
runner/summarizer sources, exact patch, raw hashes, manifests and summaries.

Validation: 217 focused tests; `UV_NO_SYNC=1 make lint` passes Ruff and strict
mypy; `UV_NO_SYNC=1 make test` passes 1,123 tests with 81 skips and 100% coverage.
The same full suite passes on Python 3.10 and free-threaded 3.14 with identical
counts and 100% coverage; `sys._is_gil_enabled()` is false on the latter. Public
API signatures pass on the maintained 3.14 runtime. The final
`make test-e2e-fastapi` gate passes all five tests from an exact staged-source
export. H003 is accepted; the next hypothesis starts from this green checkpoint.

### Measurement extension: async dispatcher key patterns

At accepted H003 checkpoint `0d8bf40`, three profiled 256-provider compilations
spend 0.784 of 0.996 instrumented seconds in dispatch generation and 0.568 seconds
in AST location walking. This identifies the remaining compiler limiter; these
profiled durations are not benchmark results. Raw profile:
`benchmark-results/campaign-2026-09-05/h004-baseline-profile.pstats` and `.txt`.

Before changing dispatch generation, add five cases in
`tests/performance/test_async_dispatch_workloads.py`. Four APP registrations
(identity/equality keys, each transient/scoped) enable the last-method cache.
All providers are synchronous, resolved through the async API. Patterns cover
repeated identity keys, repeated equality aliases, alternating identity/equality,
alternating equal-but-distinct aliases, and mixed cached/transient requests.
Repeated equality aliases hit the last-method cache after priming; alternating
equal aliases force dictionary lookup on every operation. Mixed cached requests
leave the preceding transient dispatch entry intact.

Pre-expand each pattern to exactly 1,000 keys outside timing. Retain the existing
100-iteration batch helper, three warmups and five rounds, with event-loop setup
and cleanup outside timing. Untimed assertions verify provider results, transient
freshness, cached identity, pairwise-distinct equal aliases, exact lookup-object
publication and preservation of the previous key/method by cached workflows.
Both cached values and the selected pattern are warmed before timing. Independent
measurement and lifecycle reviews find no fairness or semantic coverage blocker.
Existing genuine async-provider and lifecycle guards remain in the broad suite.

This is a measurement-only checkpoint. Five executable benchmark checks pass;
`UV_NO_SYNC=1 make lint` and `UV_NO_SYNC=1 make test` pass (1,123 tests, 86 skips,
100% coverage). The final `make test-e2e-fastapi` verification passes all five
tests from an exact staged-source export.

Preregister one fixed five-pair same-path A/A from the new checkpoint covering
all five new patterns, four warm request-cache guards and three cold sizes.
Keep the established AC/low-power-1 regime, neutral artifact names, alternating
fresh processes, empty bytecode cache and disabled cache writes. Require headline
and paired medians within 2% for all twelve cells before candidate testing.
Inspect full distributions without exclusions or calibration offsets. If this
fails, diagnose and defer runtime testing until a separately documented protocol
decision; do not sample repeatedly until the result passes. The generalized
runner requires the full checkpoint hash and freezes all source/harness inputs;
its optional absent patch performs A/A with the same child lifecycle as A/B.

### H004 hypothesis: source emission for async dispatch

Hypothesis: constructing and walking the async dispatch AST contributes material
cold compiler cost after H003. The accepted-checkpoint profile above identifies
dispatch generation as the remaining large cost.

Change: emit only async dispatch through the existing source compiler. Reuse
workflow ordering and cache-enable policy. Keep synchronous dispatch AST output
identical, removing only its now-unreachable async alternatives. Preserve the
hot last-method check, root-owned cache precheck, exact equality lookup key,
bound-method capture and publication order, equality switch and awaited fallback.
Do not fuse providers, change cache policy or inline async workflows.

Target: cold compilation throughput at 64 and 256 providers, with at least 5%
headline and paired-median gains and at least four of five paired wins at both.

Risks: source positions can alter generated instructions, especially warmed root
cache reads and method capture. Cache publication before provider failure,
scoped retry, equality aliases, dynamic methods, normalization/fallback, ownership
and cleanup must remain equivalent. Add untimed failure/retry and single-REQUEST
transient semantic guards; compare synchronous generated code fields before and
after across the existing compiler branch suite.

Accept only after the fixed 12-cell A/A passes, focused correctness/review,
five-pair focused A/B, separate allocation measurements and all 35 steady guards.
Cold-16 plus retained/peak memory at 16/64/256 remain protected; no confirmed
headline or paired regression beyond 2%, and unchanged generated-function counts.
Flagged protections receive the existing fixed five-pair confirmation, with at
most one additional five-pair extension only for genuine boundary ambiguity.
Require full quality/runtime gates, independent reviews and final FastAPI E2E.

Reject and reverse the exact candidate patch if semantics fail, either primary
gain misses the threshold, or a protected loss is confirmed. Record inconclusive
noise without selective exclusions or offsets. No runtime change is applied yet.

### H004 decision: defer before runtime edits

The fixed 12-cell A/A at `34f2dfa59ce7bfb247345de4776565d2a27abbd5` fails the
preregistered gate: the THREAD guard's exact paired median is
`+2.002987408764212%`, beyond 2%, despite a +0.933370% headline. Do not round this
into a pass. The other eleven headline/paired medians remain within 1.48%.
THREAD differences persist through whole rounds: pair-three baseline rounds are
100-102 ns versus candidate 96-97 ns; pair-five baseline 95-96 versus 92-93 ns.
Run 007 also has a 442 ns mixed-cached round against typical 225-230 ns, and
equal-alias rounds of 317-374 ns against about 308 ns. All observations remain.

Independent audit confirms pristine identical source/harness/runtime inputs,
stable AC/low-power-1 before and after every process, and empty bytecode caches.
Desktop process snapshots do not identify a causal process, scheduling effect or
layout effect. H004 is deferred, not rejected as an optimization: it has not been
implemented. Do not rerun unchanged calibration, alter iterations, subtract an
offset or reuse the A/B confirmation extension. Reopening requires a separately
documented, objectively different execution protocol/environment and one new
preregistered calibration. Pivot to allocation investigation in the meantime.

Command: `.venv/bin/python benchmark-results/campaign-2026-09-05/run_single_path_v2.py.txt h004-singlepath-calibration-aa --checkpoint 34f2dfa59ce7bfb247345de4776565d2a27abbd5 --select 'cold_compile or warm_request_cache or aresolve_dispatch_patterns'`.
All ten raw runs, 120 cells, round data, manifests, exact failed value, profile,
expected settings and reproduction scripts are archived in
`performance-evidence/2026-09-05/h004-calibration.json.gz`.
Source, tests and configuration remain byte-for-byte at the green checkpoint;
there is no runtime patch to reverse.

### Allocation investigation and measurement extension for H005

A separate allocation profile at the unchanged runtime finds 1,280 async slot
functions/code objects for 256 providers across five scope classes, but only 256
structurally distinct async code shapes. Source compilation accounts for the
largest retained allocation site. Inspection suggests about 200-239 bytes of
duplicate immutable metadata per async wrapper, roughly 205 KB gross potential
at 256 transient providers. This is not a measured saving. The 327,680 shallow
code-object bytes are not savings: executable code objects must remain distinct.
The initial `co_varnames` shallow estimate is invalid because its getter can
synthesize tuples; exclude it from allocation reasoning. Profiles remain at
`h005-allocation-profile.json` and `h005-code-clone-feasibility.json` under the
campaign artifact directory.

Directly sharing code would also share interpreter specialization state across
different scope classes. A narrower candidate would compile each async shape
once within one build, then use `CodeType.replace()` and a fresh `FunctionType`
for each other class, sharing only immutable metadata. Keep this limited to
async slot wrappers, which have no nested code constants. The local cache key is
the workflow slot and whether the wrapper performs its owner-local cache
precheck. Cross-build cache retention and scope-prefix collisions are prohibited.
Review also identifies an observable compatibility difference: replacement code
emits `code.__new__` audit events, which restrictive audit hooks may reject.

Before any runtime edit, extend `measure_compile_memory.py` with unique function,
code, async-slot function and async-slot code identity counts. Use `id(code)`,
not structural code equality. Collect these only after tracing stops, preserving
the existing registration/compile/GC/retention boundary. The executable probe
checks 215/695/2,615 distinct generated functions and code objects, and 80/320/1,280
distinct async-slot functions/code objects at 16/64/256 providers. Lint and the
full suite pass (1,123 tests, 86 skips, 100% coverage). The final FastAPI gate passes
all five tests from the exact staged-source export. The first invocation reached
Docker before its daemon was ready; the unchanged export passed once it started.

H005 is explicitly allocation-only for now. Predeclare fixed five-pair same-path
memory A/A and then A/B, with exact fingerprints and unchanged AC/low-power-1,
trace and GC settings. Memory calibration must remain within 2%. Require at least
5% retained reduction in both headline and paired medians at 64 and 256 providers,
with all five pairs improving; protect retained-16 and every peak measurement at
2%. Function and code identity counts must remain unchanged. Add focused semantic
tests before the candidate probe. The decision ceiling is "memory benefit
established; timing protection unresolved". H004's timing-calibration failure
still applies; allocation results cannot justify accepting a runtime optimization
without a separately justified timing protocol/environment decision and the
cold/35-steady protections. Park and reverse a provisional candidate afterward.

### H005 hypothesis: clone async code templates within a compilation

Baseline: `7eaaf194905675bcd6505b9b434be9748798d3a7`, with the memory identity
probe committed and all required gates green.

Hypothesis: independently compiling identical async wrapper source for each scope
duplicates immutable code metadata. A build-local template map can avoid that
duplication while preserving independent executable code and function objects.

Change: only `_build_classes`; cache the first async wrapper code by
`(workflow.slot, owner_local_cache_precheck)`. For another class with the same
shape, construct a fresh function from `template_code.replace()`, with the same
generated globals and name. Keep `_compile_slot_method` and all sync generation
unchanged. The map dies when class construction returns. No persistent cache,
shared executable code, nested-code cloning or runtime dispatch change.

Target/decision: the allocation-only rules immediately above apply unchanged.
Reject the candidate if either 64/256 retained saving misses 5%, any protected
allocation exceeds 2%, identity counts change, or focused semantics fail. Even a
passing memory result remains provisional and must be parked; there is no
accepted runtime performance commit while timing protection remains unresolved.

Risks/validation: preserve owner-prefix separation, transitive async delegation,
scope mismatch, cached identity, transient freshness, independent code/function
identities, absent closures/defaults/nested code, cross-build slot isolation and
collection while the compiler remains alive. Record the additional
`code.__new__` audit event as a compatibility difference for any later decision.

### H005 local result: memory benefit established, candidate parked

The fixed memory A/A passes with zero headline/paired median differences at all
sizes; 64/256 observations are identical across all ten probes, while 16 varies
by only 55 bytes. Fresh five-pair A/B then saves retained memory in every pair:

| Providers | Baseline retained | Candidate retained | Reduction |
| --- | ---: | ---: | ---: |
| 16 | 275,927 bytes | 261,547 bytes | 5.21% |
| 64 | 855,332 bytes | 797,668 bytes | 6.74% |
| 256 | 3,251,687 bytes | 3,018,187 bytes | 7.18% |

Both primary headline and paired medians clear 5%. Peak reductions are
1.48%/1.75%/1.84%; every function, code-object and globals count remains unchanged.
Independent audit verifies all 20 raw probes and the allocation verdict. This is
a useful allocation benefit, not an accepted overall runtime optimization.

The six new semantic cases pass on baseline and candidate. An initial collection
test failed under coverage on both versions because executing generated code
allowed the coverage machinery to retain it. The repaired test constructs the
classes without executing generated methods; it still retains the compiler and
checks weak references to all classes and code objects. Candidate lint and the
full suite pass: 1,129 tests, 86 skips, 100% coverage. Semantic review finds no
blocking lifecycle or cache-shape issue; the audit-event difference remains noted.

The exact compiler patch and validated tests are parked, with source/tests/config
restored byte-for-byte to `7eaaf19`. Two hundred focused checkpoint tests pass
after restoration. No candidate implementation is committed. All raw memory
probes, hashes, manifests, comparisons, profile caveats, candidate patch/tests and
reproduction scripts are preserved in
`performance-evidence/2026-09-05/h005-allocation.json.gz`.

Commands used the v2 same-path runner with `--checkpoint
7eaaf194905675bcd6505b9b434be9748798d3a7 --kind memory`, labels
`h005-singlepath-memory-aa` and `h005-singlepath-memory-ab`; only the latter adds
`--patch benchmark-results/campaign-2026-09-05/h005-candidate.patch`.
Timing protection remains unresolved on the Mac. Investigate one separately
preregistered Linux CI environment, with calibration and comparison in the same
job; keep all Mac and Linux evidence separate.

### H005 Linux timing protocol: one new environment, one calibration attempt

H004's local timing calibration remains failed. A GitHub-hosted Ubuntu 24.04 VM
is an objectively different environment, with a different OS, architecture and
scheduler. Preregister one Linux job to establish its own calibration and timing
protections; never pool its observations with the Mac evidence. This is a
Linux-specific acceptance investigation, not another unchanged local A/A retry.
The hosted VM does not guarantee exclusive physical CPU or a known host power
policy. Record the image, CPU, affinity, quota, load, processes and cumulative
CPU/steal counters; do not claim control of the underlying host.

The machine-readable protocol is
`performance-evidence/2026-09-05/h005-linux-protocol.json`. Freeze subject
`7eaaf194905675bcd6505b9b434be9748798d3a7`, Python 3.14.6 with GIL enabled, uv
0.11.26, the existing dependency lock, exact candidate patch/archive hashes and
all workload settings. Use a separate controller checkout and one subject
checkout/venv for every role and phase in a single job. Install dependencies
before measurements. Launch the absolute subject interpreter, disable bytecode
writes, and verify source, harness, runtime and dependency metadata before and
after each process. Apply/reverse only the archived compiler patch. Odd pairs run
base/work; even pairs work/base. Every initial series has exactly five independent
fresh-process pairs. Preserve all individual rounds and all partial artifacts.

Run these gates in order:

1. Timing A/A: the frozen 12 cells (three cold, four warm-cache and five async
   dispatch patterns). Both absolute headline and paired-median effects must be
   at most 2%, without rounding. Any failure defers H005; do not rerun calibration.
2. Memory A/A: all three sizes, retained and peak, within the same 2% bounds.
   Require the expected independent function/code counts and one globals dict.
3. Memory A/B: at both 64 and 256 providers, require at least 5% retained saving
   in both headline and paired medians, with all five pairs improving. Protect
   retained-16 and every peak metric at a maximum 2% regression.
4. Timing A/B: all 38 frozen cells, protecting every cold and steady workload at
   2%. H005 does not require or claim a primary throughput gain.
5. For protected flags (either headline or paired effect below -2%), run separate
   five-pair confirmations of the flagged timing nodes and/or the memory probe.
   Complete both initial confirmation groups before any extension. Clear
   failures reject. A result is ambiguous only when the two threshold decisions
   disagree or either effect is within 0.25 percentage points of -2%. This band
   triggers an extension; it does not relax acceptance or estimate confidence.
6. If no clear failure exists, permit one extension wave for ambiguous cells,
   grouped by measurement kind, numbered pairs 6-10. Recompute from all ten
   dedicated confirmation pairs. Both effects at least -2% pass; both below -2%
   reject; disagreement is inconclusive. Never pool initial broad A/B samples,
   average block medians, remove outliers, subtract calibration offsets or extend
   again. Memory probes always retain all three sizes, though only flagged
   metrics drive the confirmation decision.

Use the existing Benchmarks workflow's manual experiment input. The experiment
has read-only repository permissions, its own non-cancelling concurrency group,
a 70-minute controller budget, bounded child/setup commands and a 90-minute job
limit. It must stop and verify its owned process group before source restoration,
including after normal leader exit, timeout and interruption. Initialization,
measurement and restoration failures must leave diagnostic evidence. Upload the
complete or partial directory regardless of outcome. Dispatch exactly once from
the committed controller revision; record the workflow run ID afterward.

Independent compiler/lifecycle and measurement reviewers approved the corrected
controller. Regression checks cover absent optional files in the frozen subject,
canonical-only confirmation metadata, wrong child runtime, exact arithmetic and
sample validation, global confirmation staging, calibration stopping, deferred
launch interruption, surviving descendants and failure evidence. Archived H004
rounds and all H005 allocation probes validate against the new readers. The
candidate remains parked until the experiment and required semantic/quality
checks support a decision. A Linux calibration failure means defer/pivot, not a
second hosted attempt chosen for a more favorable sample.

Controller quality checkpoint: all 27 focused regression cases pass, including
validation of 10 archived timing runs and 20 allocation probes. A clean export of
the actual pinned subject passes the input-hash and candidate/apply/restore check
with both optional files absent. `make lint` passes (Ruff and strict mypy),
`make test` passes 1,150 tests with 86 skips and 100% coverage, and the final
`make test-e2e-fastapi` passes all five tests from the exact staged-source export.
No library implementation change is included in this checkpoint.
