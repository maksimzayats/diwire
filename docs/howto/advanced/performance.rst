.. meta::
   :description: diwire performance: benchmark methodology, reproducible results, and a scenario-by-scenario comparison table.

Performance
===========

This page is the only place where diwire documentation compares benchmark results against other DI libraries.

Why it’s fast
-------------

- **Compiled resolver code paths**: ``compile()`` generates a resolver specialized to your registrations.
- **Strict mode hot-path rebinding**: with ``autoregister_concrete_types=False``, container entrypoints can be rebound to
  the compiled resolver for lower overhead.
- **Minimal overhead**: diwire has zero runtime dependencies.

Benchmark methodology
---------------------

To reproduce locally:

.. code-block:: bash

   make benchmark-report

Benchmarked library versions:

- diwire: editable checkout at commit ``49488db25e58a6a4af4e55edbd4d84e300c124cc`` (branch ``v1``, dirty working tree)
- dishka: ``1.7.2``
- rodi: ``2.0.8``

Environment (from ``benchmark-results/raw-benchmark.json``):

- Python: CPython ``3.10.19``
- OS/CPU: Darwin arm64 (Apple M1 Pro)

Methodology details for diwire in these benchmarks:

- Strict mode container setup: ``autoregister_concrete_types=False`` and ``autoregister_dependencies=False``
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
     - 3815590
     - 2761140
     - 880489
     - 1.38×
     - 4.33×
   * - enter_close_scope_resolve_100_instance
     - 62581
     - 35165
     - 11798
     - 1.78×
     - 5.30×
   * - enter_close_scope_resolve_once
     - 2315085
     - 1549029
     - 352474
     - 1.49×
     - 6.57×
   * - enter_close_scope_resolve_scoped_100
     - 74324
     - 44122
     - 37296
     - 1.68×
     - 1.99×
   * - resolve_deep_transient_chain
     - 1122660
     - 466809
     - 478690
     - 2.40×
     - 2.35×
   * - resolve_mixed_lifetimes
     - 1367809
     - 744854
     - 355817
     - 1.84×
     - 3.84×
   * - resolve_scoped
     - 1868270
     - 1104477
     - 636342
     - 1.69×
     - 2.94×
   * - resolve_singleton
     - 6056235
     - 2494940
     - 3403712
     - 2.43×
     - 1.78×
   * - resolve_transient
     - 5079473
     - 2100024
     - 2298482
     - 2.42×
     - 2.21×
   * - resolve_wide_transient_graph
     - 1422929
     - 685436
     - 608329
     - 2.08×
     - 2.34×

Summary (computed from the table above):

- diwire is the top ops/s implementation in all benchmark scenarios in this strict-mode run.
- Speedup over rodi ranges from **1.38×** to **2.43×**.
- Speedup over dishka ranges from **1.78×** to **6.57×**.

Results vary by environment, Python version, and hardware. Re-run ``make benchmark-report`` on your target runtime
before drawing final conclusions for production workloads.
