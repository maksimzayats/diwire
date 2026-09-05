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
