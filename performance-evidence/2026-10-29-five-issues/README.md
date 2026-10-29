# Five proven optimization targets

Five independent targets passed the declared proof rules. The library source on this branch stays at baseline `6f225bf30bc8dc5e9f0f907c126396534ad6aef9`. Apply one proof patch at a time in a separate checkout.

| ID | Target | Median throughput gain | Bootstrap 95% interval | Positive pairs |
| --- | --- | ---: | --- | --- |
| h001 | Reuse async generator context-manager factories | +21.28% | 20.13% to 21.94% | 7/7 |
| h002 | Cache explicit scope transition plans | +23.77% | 23.62% to 25.11% | 7/7 |
| h003 | Resolve all-sync public collections without coroutine wrappers | +32.85% | 30.75% to 34.10% | 7/7 |
| h004 | Avoid generator allocations while propagating cleanup flags | +37.24% | 36.67% to 38.37% | 7/7 |
| h005 | Index generic templates by their outer type | +9.07% | 8.89% to 9.77% | 7/7 |

The gain is specific to each workload in `summary.json`. These percentages must not be added or used as an application-wide estimate.

## Proof method

The primary study used a dedicated Ubuntu 24.04 runner, Linux x86_64, AMD EPYC 9V74, GIL-enabled CPython 3.14.10, one pinned CPU, and the same locked dependencies. Each candidate passed a three-pair identical-source calibration. The study then kept seven alternating fresh-process baseline/candidate pairs and every raw round. The useful-gain floor was 5%. Every primary won all seven pairs, had a positive lower bootstrap bound, and met the 10% per-process variation limit.

The ACTION scope control had noisy short rounds. One fixed seven-pair confirmation used five times the same work per round. It passed. The original rounds stay in the archive. Broader startup, registration, and dense-compile costs used three-pair screens. Every saved screen passed the 5% regression bound and 10% variation limit. The full canonical timing matrix remains a merge check.

## Behavior and quality

Each proof version passed `make lint`, strict mypy, and `make test`: 1,564 tests passed, 9 skipped, with 100% configured statement and branch coverage. Each also passed 166 focused checks on Python 3.10 and free-threaded Python 3.14. The final FastAPI verification passed 11 tests for each of the five versions.

The research ran the separate focused behavior file through `PYTEST_ADDOPTS`. Move its relevant checks into the normal test modules when implementing an issue. The runtime patch alone is not a complete test change.

The sparse generic check confirmed 128 provider registrations and all 64 closed keys immediately after compile, before any consumer resolution. Profiling counted 16,384 template match attempts in the baseline and 64 in the indexed version. Profile times are not benchmark results.

H002 received a lint cleanup after timing: an unused bootstrap variable became a direct return. The timed scope-entry function is identical at the AST level. `h002-measured.patch.txt` and `h002-lint-cleanup-proof.json` retain the measured version and its source hash. The final `h002.patch` passes lint.

## Costs and limits

The saved three-pair ARM64 memory probe found 30,944 extra retained bytes for 64 unused async generator wrappers, 315 bytes for the visited scope-plan cache, 277 bytes for the synchronous collection key set, 424 bytes in the cleanup registration graph, and 20,848 bytes for the 256-root generic index graph. These measurements are separate from the x86_64 timing study.

The mixed collection control measured -1.72%, and the default REQUEST scope control measured -1.22%. Both stayed within the declared 5% bound. The generic index keeps a full-scan path for nonstandard origins and metaclasses.

## Prior results remain visible

Recent history showed that the earlier async factory wins were already merged in PRs #306 and #308. They were excluded. The past ledger also rejected skipping zero-parameter type hints because it can change behavior, and found registry-length copy removal too small to justify a change.

The local first calibration failed. Larger adjacent batches passed the next declared calibration. Local full generic compile gains of 4.20% for the cleanup reducer and 0.846% for the dense generic index did not clear the 5% floor. A local late-registration target had excess variation. The local sparse generic control failed calibration. All remain in `local-evidence.tar.gz`.

The hosted study is a separate study on another machine. Its accepted claims are late registration and sparse generic compile, not broad compile speed. Its primary estimates were not repeated after acceptance.

## Hosted stages

- [Primary study](https://github.com/maksimzayats/diwire/actions/runs/40891772941): all five primary targets passed. The job then stopped because the unused-generator control fixture omitted required cleanup.
- [First cost controls](https://github.com/maksimzayats/diwire/actions/runs/40894254101): the unused-generator compile screens passed. The registration fixture then tried to close an uncompiled container and stopped.
- [Remaining cost controls](https://github.com/maksimzayats/diwire/actions/runs/40894626960): the corrected registration and compile screens passed.

The failures are retained. The final decision uses completed records from these stages and independent raw-data audits. A workflow status alone is not the acceptance record.

## Repeat one target on Linux

Fetch this research branch with full history. Install the locked environment, then choose a new output directory:

```sh
uv sync --locked --python 3.14.10 --group dev --group docs
STUDY_CASE=h001 STUDY_ROOT=/tmp/diwire-h001-proof uv run --locked python performance-evidence/2026-10-29-five-issues/hosted_study.py.txt
```

Choose `h001` through `h005`. Leave `STUDY_CASE` unset to run all five. An existing output directory causes a stop, so earlier evidence is preserved.

The driver creates one clean baseline worktree and five isolated candidate worktrees. It applies the bundled patches, checks behavior, records source and input hashes, calibrates the selected group, measures the paired target, and checks broader costs.

For a quality repeat in a candidate worktree, install its locked dev/docs environment. Copy `test_proof_semantics.py.txt` to a temporary Python test file. Run `make lint`, then `PYTEST_ADDOPTS=/absolute/path/to/test_proof_semantics.py make test`. Run `make test-e2e-fastapi` last.

## Files

`summary.json` is the decision record. `h001.patch` through `h005.patch` are separate proof changes. `hosted-evidence.tar.gz` holds raw hosted rounds, manifests, logs, and confirmations. `local-evidence.tar.gz` holds local measurements, counts, memory probes, quality logs, failed attempts, and review reports. The `.py.txt` files are executable research inputs stored outside the production test tree.
