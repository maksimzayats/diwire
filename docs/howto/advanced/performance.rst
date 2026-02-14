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

Resolve-only comparison table (includes ``punq``):

.. code-block:: bash

   make benchmark-report-resolve

Benchmarked library versions:

- diwire: editable checkout at commit ``7d467211568d7955a92f929e613450521cc1b114`` (branch ``comparison-table``, dirty working tree)
- dishka: ``1.8.0``
- punq: ``0.7.0``
- rodi: ``2.0.8``
- wireup: ``2.7.0``

Environment (from ``benchmark-results/raw-benchmark.json``):

- Python: CPython ``3.14.2``
- OS/CPU: Darwin arm64 (Apple M1 Pro)

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
     - 6518660
     - 4524061
     - 860796
     - 1971905
     - 1.44×
     - 7.57×
     - 3.31×
   * - enter_close_scope_resolve_100_instance
     - 87070
     - 58303
     - 11494
     - 67470
     - 1.49×
     - 7.57×
     - 1.29×
   * - enter_close_scope_resolve_once
     - 3676678
     - 2510567
     - 482201
     - 1481135
     - 1.46×
     - 7.62×
     - 2.48×
   * - enter_close_scope_resolve_scoped_100
     - 93662
     - 72891
     - 38950
     - 67401
     - 1.28×
     - 2.40×
     - 1.39×
   * - resolve_deep_transient_chain
     - 1816309
     - 733845
     - 754110
     - 915855
     - 2.48×
     - 2.41×
     - 1.98×
   * - resolve_mixed_lifetimes
     - 2271693
     - 1107436
     - 382173
     - 898465
     - 2.05×
     - 5.94×
     - 2.53×
   * - resolve_scoped
     - 2840744
     - 1840370
     - 591232
     - 1351828
     - 1.54×
     - 4.80×
     - 2.10×
   * - resolve_singleton
     - 6978367
     - 3543417
     - 3441938
     - 5128950
     - 1.97×
     - 2.03×
     - 1.36×
   * - resolve_transient
     - 5397358
     - 2682653
     - 2464092
     - 5083800
     - 2.01×
     - 2.19×
     - 1.06×
   * - resolve_wide_transient_graph
     - 1849443
     - 832000
     - 782193
     - 1285315
     - 2.22×
     - 2.36×
     - 1.44×

Summary (computed from the table above):

- diwire is the top ops/s implementation in all benchmark scenarios in this strict-mode run.
- Speedup over rodi ranges from **1.28×** to **2.48×**.
- Speedup over dishka ranges from **2.03×** to **7.62×**.
- Speedup over wireup ranges from **1.06×** to **3.31×**.

Results vary by environment, Python version, and hardware. Re-run ``make benchmark-report`` on your target runtime
before drawing final conclusions for production workloads.

Resolve-only comparisons (includes punq)
----------------------------------------

``punq`` has no request scopes, so it is included only in resolve-only scenarios without scopes.

Source of truth: ``benchmark-results/benchmark-table-resolve.json`` (rendered to
``benchmark-results/benchmark-table-resolve.md``).

.. list-table::
   :header-rows: 1

   * - Scenario
     - diwire (ops/s)
     - rodi (ops/s)
     - dishka (ops/s)
     - wireup (ops/s)
     - punq (ops/s)
     - Speedup (diwire/rodi)
     - Speedup (diwire/dishka)
     - Speedup (diwire/wireup)
     - Speedup (diwire/punq)
   * - resolve_deep_transient_chain
     - 1764124
     - 722462
     - 736488
     - 892946
     - 10730
     - 2.44×
     - 2.40×
     - 1.98×
     - 164.40×
   * - resolve_singleton
     - 5861293
     - 3441404
     - 3406823
     - 5022682
     - 2368448
     - 1.70×
     - 1.72×
     - 1.17×
     - 2.47×
   * - resolve_transient
     - 5231024
     - 2709566
     - 2450974
     - 4974766
     - 23905
     - 1.93×
     - 2.13×
     - 1.05×
     - 218.82×
   * - resolve_wide_transient_graph
     - 1911370
     - 827975
     - 767232
     - 1278817
     - 4921
     - 2.31×
     - 2.49×
     - 1.49×
     - 388.44×

Summary (computed from the table above):

- Speedup over wireup ranges from **1.05×** to **1.98×** in these resolve-only scenarios.
- Speedup over punq ranges from **2.47×** to **388.44×** in these resolve-only scenarios.
