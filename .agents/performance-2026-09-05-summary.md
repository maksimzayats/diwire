# DIWire performance campaign, 5 September 2026

The campaign is closed at the user's request. Four runtime optimizations were
accepted and retained on `codex/perf-2026-09-05` in [draft PR #263](https://github.com/maksimzayats/diwire/pull/263). The last
hypothesis failed its calibration gate and contributed no runtime change.

## Accepted changes

These are results from separate controlled experiments, not pooled or compounded
estimates. Positive throughput percentages mean more operations per second;
startup and memory percentages below are reductions.

| Change | Representative accepted result | Commit |
| --- | --- | --- |
| Async wrappers call the synchronous slot when the workflow is synchronous | 2.830 to 6.259 million ops/s; +121.18% headline, +121.28% paired. Async class-scope lifecycle +61.40%; sync-generator lifecycle +19.96%. | `b2fc322` |
| Generated functions share an exact dictionary namespace; other mappings are copied | Retained compile allocations at 64/256 providers fell 84.26%/95.46%. At 256: 71.29 MB to 3.24 MB. Compile throughput +6.48%/+21.57% headline. | `0196cd2` |
| Generic slot wrappers use the existing source compiler | First-compile throughput at 64/256 providers improved 6.597%/7.077% headline and 6.904%/6.911% paired, with 5/5 positive pairs at each size. | `0d8bf40` |
| Optional settings integration imports when inspection first needs it | With Pydantic/settings installed, package import fell 127.805 ms to 52.916 ms (58.5967% headline, 58.3371% paired); explicit registration/first resolution fell 57.4569% headline. | `932802ec` |

The startup measurements use fresh processes and prepared bytecode, excluding
interpreter launch. They do not promise the same savings when optional packages
are absent or autoregistration immediately needs their integration. Accepted
experiments retained their full protected workloads and required confirmations.
The source diff contains only these four mechanisms and their documentation.
Public API signatures remain unchanged.

## Final cumulative canonical comparison

One fixed 25-pair series compared original revision
`5b73a0d90b0f22e3d7004f08456f2b2ab8b5ac2a` with final runtime checkpoint
`9be5102907d882ab99f17c6ff72e0ec72c52eea0`, through the same clean detached
checkout, interpreter, dependency environment and bytecode-cache path. All 17
canonical DIWire workloads and every original round were retained. Later wrap-up
commits add only evidence/reporting; their runtime matches that checkpoint.

The headline geometric mean is **+0.3822%**. The worst headline/paired effects
are **-0.5539%/-0.4331%**. The generated scoped grid measured
+3.4853%/+3.8008%, with 25/25 positive pairs. This final readout is descriptive;
there were no retries, confirmations, exclusions or additional optimizations.
Earlier per-hypothesis experiments are the acceptance evidence. The original
comparison checkout was restored and the user's main checkout was untouched.

| Canonical workload | Headline throughput | Paired throughput | Positive pairs |
| --- | ---: | ---: | ---: |
| enter close scope no resolve | -0.2506% | -0.2184% | 9/25 |
| enter close scope resolve 100 | +0.2002% | +0.0829% | 14/25 |
| enter close scope resolve generator request try finally | +0.3065% | +0.2132% | 14/25 |
| enter close scope resolve once | +0.1060% | +0.1010% | 13/25 |
| enter close scope resolve open generic scoped | +0.6066% | +1.0186% | 16/25 |
| enter close scope resolve scoped 100 | +0.3250% | +0.1934% | 15/25 |
| resolve deep transient chain | -0.0019% | +0.0163% | 13/25 |
| resolve generated scoped grid | +3.4853% | +3.8008% | 25/25 |
| resolve mixed lifetimes | -0.3348% | -0.4188% | 9/25 |
| resolve open generic transient | +0.8609% | +0.8539% | 15/25 |
| resolve scoped | -0.0302% | -0.0337% | 12/25 |
| resolve scoped with registered open closed generics | -0.2823% | +0.1298% | 14/25 |
| resolve scoped with registered open closed generics pair alternating | -0.5539% | -0.4331% | 9/25 |
| resolve scoped with registered open closed generics pair same | +0.1402% | -0.0482% | 12/25 |
| resolve singleton | +0.7289% | -0.1699% | 10/25 |
| resolve transient | +0.3607% | +1.0200% | 14/25 |
| resolve wide transient graph | +0.8944% | +1.0414% | 18/25 |

## Deferred and rejected work

- H004/H004-R1 async dispatcher source emission: calibration failed; no runtime patch retained.
- H005 code-template reuse: memory results were promising, but timing calibration failed; its tested prototype was reversed.
- H006 unused async helper allocation: screened, not implemented before wrap-up.
- H008 skipping hints for zero-parameter providers: rejected because annotation evaluation can have observable effects or exceptions.
- H009 counting generic registrations without copying: rejected at screening; generously attributed profiled cost was below 0.5% of compilation.
- H010 direct cleanup reduction: the disposable-process screen suggested +5.49% at 256 generic consumers, but the one formal startup calibration failed (paired -2.192856% between identical-code roles). No runtime candidate or later experiment phase followed; the screen is not an accepted gain.

## Verification and evidence

Independent agents reviewed hot paths, lifecycle/concurrency semantics, benchmark
fairness, raw arithmetic and the final runtime scope. Every accepted implementation
passed lint/strict typing, public API checks and 100% statement/branch coverage;
Python 3.10 and free-threaded behavior were checked.

Final verification on the accepted source: `UV_NO_SYNC=1 make lint` passed
(292 files formatted, 190 files typed), and `UV_NO_SYNC=1 make test` passed
1,170 tests with 93 skips and 100% statement/branch coverage (4,101 statements,
1,516 branches). The final implementation verification was
`make test-e2e-fastapi` against an exact staged-source export: all five tests
passed, the command exited successfully and its containers were removed.
Only closing reports/evidence were added afterward. Final verification logs
are preserved in `performance-evidence/2026-09-05/final-verification.json.gz`.

The complete protocol, exact commands, environments, thresholds, decisions and
per-hypothesis validation are in `performance-2026-09-05.md`. Hash-verified raw
results and reproduction controllers are committed under
`performance-evidence/2026-09-05/`; operational smoke runs and failed gates remain
separate from accepted results. No unvalidated optimization remains in the library.
