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

- diwire: editable checkout at commit ``6522c9737e1564239e15642a701cdf70407e455d`` (branch ``update-assembly``)
- dishka: ``1.8.0``
- punq: ``0.7.0``
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
     - 8994383
     - 5845207
     - 1053050
     - 2574708
     - 1.54×
     - 8.54×
     - 3.49×
   * - enter_close_scope_resolve_100_instance
     - 439797
     - 72806
     - 14590
     - 88382
     - 6.04×
     - 30.14×
     - 4.98×
   * - enter_close_scope_resolve_once
     - 7372977
     - 3025993
     - 626813
     - 1867059
     - 2.44×
     - 11.76×
     - 3.95×
   * - enter_close_scope_resolve_scoped_100
     - 206273
     - 83922
     - 48224
     - 87925
     - 2.46×
     - 4.28×
     - 2.35×
   * - resolve_deep_transient_chain
     - 2833062
     - 1059470
     - 963263
     - 1276576
     - 2.67×
     - 2.94×
     - 2.22×
   * - resolve_mixed_lifetimes
     - 3167472
     - 1500569
     - 523542
     - 1154623
     - 2.11×
     - 6.05×
     - 2.74×
   * - resolve_scoped
     - 4408562
     - 2443622
     - 790101
     - 1738778
     - 1.80×
     - 5.58×
     - 2.54×
   * - resolve_singleton
     - 16814447
     - 4588217
     - 4697909
     - 7106521
     - 3.66×
     - 3.58×
     - 2.37×
   * - resolve_transient
     - 12229474
     - 2966293
     - 3083285
     - 6664490
     - 4.12×
     - 3.97×
     - 1.84×
   * - resolve_wide_transient_graph
     - 3522243
     - 1138263
     - 987064
     - 1663441
     - 3.09×
     - 3.57×
     - 2.12×

Summary (computed from the table above):

- diwire is the top ops/s implementation in all benchmark scenarios in this strict-mode run.
- Speedup over rodi ranges from **1.54×** to **6.04×**.
- Speedup over dishka ranges from **2.94×** to **30.14×**.
- Speedup over wireup ranges from **1.84×** to **4.98×**.

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
     - 2778542
     - 1064436
     - 1042018
     - 1261015
     - 13783
     - 2.61×
     - 2.67×
     - 2.20×
     - 201.59×
   * - resolve_singleton
     - 16181513
     - 4631002
     - 4644919
     - 6962071
     - 3073187
     - 3.49×
     - 3.48×
     - 2.32×
     - 5.27×
   * - resolve_transient
     - 12432966
     - 3494551
     - 3318816
     - 6848240
     - 32310
     - 3.56×
     - 3.75×
     - 1.82×
     - 384.80×
   * - resolve_wide_transient_graph
     - 3555619
     - 1096104
     - 1027847
     - 1524611
     - 5969
     - 3.24×
     - 3.46×
     - 2.33×
     - 595.70×

Summary (computed from the table above):

- Speedup over wireup ranges from **1.82×** to **2.33×** in these resolve-only scenarios.
- Speedup over punq ranges from **5.27×** to **595.70×** in these resolve-only scenarios.
