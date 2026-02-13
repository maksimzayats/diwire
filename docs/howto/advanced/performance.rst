.. meta::
   :description: diwire performance: benchmark methodology, reproducible results, and a scenario-by-scenario comparison table.

Performance
===========

This page is the only place where diwire documentation compares benchmark results against other DI libraries.

Why it’s fast
-------------

- **Compiled resolver code paths**: ``compile()`` generates a resolver specialized to your registrations.
- **Strict mode hot-path rebinding**: with ``missing_policy=MissingPolicy.ERROR``, container entrypoints can be rebound to
  the compiled resolver for lower overhead.
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

- diwire: editable checkout at commit ``48a6519f831372da5d7d5ab98345ba69778dc3f0`` (branch ``v1``, dirty working tree)
- dishka: ``1.7.2``
- punq: ``0.7.0``
- rodi: ``2.0.8``

Environment (from ``benchmark-results/raw-benchmark.json``):

- Python: CPython ``3.12.5``
- OS/CPU: Darwin arm64 (Apple M1 Pro)

Methodology details for diwire in these benchmarks:

- Strict mode container setup: ``missing_policy=MissingPolicy.ERROR`` and
  ``dependency_registration_policy=DependencyRegistrationPolicy.IGNORE``
- All benchmark registrations are explicit.
- ``container.compile()`` is called once after registration setup and before timed loops to measure compiled steady-state entrypoints.

Results (diwire vs rodi and dishka)
-----------------------------------

Source of truth: ``benchmark-results/benchmark-table.json`` (rendered to ``benchmark-results/benchmark-table.md``).

.. list-table::
   :header-rows: 1

   * - Scenario
     - diwire (ops/s)
     - rodi (ops/s)
     - dishka (ops/s)
     - Speedup (diwire/rodi)
     - Speedup (diwire/dishka)
   * - enter_close_scope_no_resolve
     - 4890376
     - 3404710
     - 1000090
     - 1.44×
     - 4.89×
   * - enter_close_scope_resolve_100_instance
     - 83981
     - 54992
     - 13274
     - 1.53×
     - 6.33×
   * - enter_close_scope_resolve_once
     - 3134287
     - 2094023
     - 403971
     - 1.50×
     - 7.76×
   * - enter_close_scope_resolve_scoped_100
     - 95893
     - 78328
     - 40845
     - 1.22×
     - 2.35×
   * - resolve_deep_transient_chain
     - 1357614
     - 710215
     - 653016
     - 1.91×
     - 2.08×
   * - resolve_mixed_lifetimes
     - 1590693
     - 1001925
     - 421357
     - 1.59×
     - 3.78×
   * - resolve_scoped
     - 2039077
     - 1486316
     - 692814
     - 1.37×
     - 2.94×
   * - resolve_singleton
     - 6539556
     - 3260371
     - 3606062
     - 2.01×
     - 1.81×
   * - resolve_transient
     - 5232422
     - 2514313
     - 2390968
     - 2.08×
     - 2.19×
   * - resolve_wide_transient_graph
     - 1665818
     - 761640
     - 679907
     - 2.19×
     - 2.45×

Summary (computed from the table above):

- diwire is the top ops/s implementation in all benchmark scenarios in this strict-mode run.
- Speedup over rodi ranges from **1.22×** to **2.19×**.
- Speedup over dishka ranges from **1.81×** to **7.76×**.

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
     - punq (ops/s)
     - Speedup (diwire/rodi)
     - Speedup (diwire/dishka)
     - Speedup (diwire/punq)
   * - resolve_deep_transient_chain
     - 1304305
     - 711307
     - 639173
     - 12450
     - 1.83×
     - 2.04×
     - 104.76×
   * - resolve_singleton
     - 6636706
     - 3212902
     - 3593792
     - 2004608
     - 2.07×
     - 1.85×
     - 3.31×
   * - resolve_transient
     - 5290168
     - 2492831
     - 2415740
     - 34197
     - 2.12×
     - 2.19×
     - 154.70×
   * - resolve_wide_transient_graph
     - 1659712
     - 781090
     - 662153
     - 6174
     - 2.12×
     - 2.51×
     - 268.84×

Summary (computed from the table above):

- Speedup over punq ranges from **3.31×** to **268.84×** in these resolve-only scenarios.
