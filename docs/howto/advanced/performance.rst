.. meta::
   :description: diwire performance: benchmark methodology, reproducible results, and a scenario-by-scenario comparison table.

Performance
===========

This page is the only place where diwire documentation compares benchmark results against other DI libraries.

Why it’s fast
-------------

- **Compiled resolver code paths**: ``compile()`` generates a resolver specialized to your registrations.
- **Strict mode hot-path rebinding**: in strict mode (opt-in via
  ``missing_policy=MissingPolicy.ERROR`` and
  ``dependency_registration_policy=DependencyRegistrationPolicy.IGNORE``),
  container entrypoints can be rebound to the compiled resolver for lower overhead.
- **Minimal overhead**: diwire has zero runtime dependencies.

Benchmark methodology
---------------------

To reproduce locally:

.. code-block:: bash

   make benchmark-report

Resolve-only comparison table (scope-capable libraries):

.. code-block:: bash

   make benchmark-report-resolve

Benchmarked library versions:

- diwire: editable checkout at commit ``4d99b2cf48a1dc51af0f13a158a13073693fa71b`` (branch ``main``)
- dishka: ``1.8.0``
- rodi: ``2.0.8``
- wireup: ``2.7.0``

Environment (from ``benchmark-results/raw-benchmark.json``):

- Python: CPython ``3.14.3``
- OS/CPU: Darwin arm64 (Apple M3 Pro)

Methodology details for diwire in these benchmarks:

- Strict mode container setup: ``missing_policy=MissingPolicy.ERROR`` and
  ``dependency_registration_policy=DependencyRegistrationPolicy.IGNORE``
- All benchmark registrations are explicit.
- ``container.compile()`` is called once after registration setup and before timed loops to measure compiled steady-state entrypoints.

Results (diwire vs rodi, dishka, and wireup)
--------------------------------------------

Source of truth: ``benchmark-results/benchmark-table.json`` (rendered to ``benchmark-results/benchmark-table.md``).

.. list-table::
   :header-rows: 1

   * - Scenario
     - diwire (ops/s)
     - rodi (ops/s)
     - dishka (ops/s)
     - wireup (ops/s)
     - Speedup (diwire/rodi)
     - Speedup (diwire/dishka)
     - Speedup (diwire/wireup)
   * - enter_close_scope_no_resolve
     - 8738649
     - 5450215
     - 970593
     - 2409436
     - 1.60×
     - 9.00×
     - 3.63×
   * - enter_close_scope_resolve_100_instance
     - 406013
     - 70632
     - 13277
     - 82257
     - 5.75×
     - 30.58×
     - 4.94×
   * - enter_close_scope_resolve_once
     - 6972504
     - 2940919
     - 546914
     - 1788494
     - 2.37×
     - 12.75×
     - 3.90×
   * - enter_close_scope_resolve_scoped_100
     - 223004
     - 91611
     - 48931
     - 81391
     - 2.43×
     - 4.56×
     - 2.74×
   * - resolve_deep_transient_chain
     - 2614862
     - 928510
     - 954487
     - 1198976
     - 2.82×
     - 2.74×
     - 2.18×
   * - resolve_generated_scoped_grid
     - 126503
     - 46418
     - 27986
     - 38994
     - 2.73×
     - 4.52×
     - 3.24×
   * - resolve_mixed_lifetimes
     - 3001207
     - 1471547
     - 461337
     - 1087162
     - 2.04×
     - 6.51×
     - 2.76×
   * - resolve_scoped
     - 4179979
     - 2313050
     - 718835
     - 1674933
     - 1.81×
     - 5.81×
     - 2.50×
   * - resolve_singleton
     - 16169370
     - 4424704
     - 4535111
     - 6611818
     - 3.65×
     - 3.57×
     - 2.45×
   * - resolve_transient
     - 12075301
     - 3317453
     - 3001516
     - 6192395
     - 3.64×
     - 4.02×
     - 1.95×
   * - resolve_wide_transient_graph
     - 3405589
     - 1069481
     - 999023
     - 1555711
     - 3.18×
     - 3.41×
     - 2.19×

Summary (computed from the table above):

- diwire is the top ops/s implementation in all benchmark scenarios in this strict-mode run.
- Speedup over rodi ranges from **1.60×** to **5.75×**.
- Speedup over dishka ranges from **2.74×** to **30.58×**.
- Speedup over wireup ranges from **1.95×** to **4.94×**.

Results vary by environment, Python version, and hardware. Re-run ``make benchmark-report`` on your target runtime
before drawing final conclusions for production workloads.

Resolve-only comparisons (scope-capable libraries)
--------------------------------------------------

Source of truth: ``benchmark-results/benchmark-table-resolve.json`` (rendered to
``benchmark-results/benchmark-table-resolve.md``).

.. list-table::
   :header-rows: 1

   * - Scenario
     - diwire (ops/s)
     - rodi (ops/s)
     - dishka (ops/s)
     - wireup (ops/s)
     - Speedup (diwire/rodi)
     - Speedup (diwire/dishka)
     - Speedup (diwire/wireup)
   * - resolve_deep_transient_chain
     - 2604232
     - 1019443
     - 958980
     - 1234597
     - 2.55×
     - 2.72×
     - 2.11×
   * - resolve_generated_scoped_grid
     - 115874
     - 45424
     - 27992
     - 37413
     - 2.55×
     - 4.14×
     - 3.10×
   * - resolve_singleton
     - 15840413
     - 4348967
     - 4497497
     - 6702791
     - 3.64×
     - 3.52×
     - 2.36×
   * - resolve_transient
     - 11647805
     - 3390537
     - 3043317
     - 6422295
     - 3.44×
     - 3.83×
     - 1.81×
   * - resolve_wide_transient_graph
     - 3343088
     - 1005581
     - 977814
     - 1486825
     - 3.32×
     - 3.42×
     - 2.25×

Summary (computed from the table above):

- Speedup over rodi ranges from **2.55×** to **3.64×** in these resolve-only scenarios.
- Speedup over dishka ranges from **2.72×** to **4.14×** in these resolve-only scenarios.
- Speedup over wireup ranges from **1.81×** to **3.10×** in these resolve-only scenarios.
