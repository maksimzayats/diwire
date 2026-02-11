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

- diwire: editable checkout at commit ``6fc0ab21cca9d8323b550ba5358bcac4fa37bcbf`` (branch ``v1``, dirty working tree)
- dishka: ``1.7.2``
- rodi: ``2.0.8``

Environment (from ``benchmark-results/raw-benchmark.json``):

- Python: CPython ``3.10.19``
- OS/CPU: Darwin arm64 (Apple M1 Pro)

Results (diwire vs dishka)
--------------------------

.. list-table::
   :header-rows: 1

   * - Scenario
     - diwire (ops/s)
     - dishka (ops/s)
     - Speedup
   * - enter_close_scope_no_resolve
     - 2204933
     - 792336
     - 2.78×
   * - enter_close_scope_resolve_100_instance
     - 62853
     - 8954
     - 7.02×
   * - enter_close_scope_resolve_once
     - 1634524
     - 391320
     - 4.18×
   * - enter_close_scope_resolve_scoped_100
     - 64794
     - 36815
     - 1.76×
   * - resolve_deep_transient_chain
     - 723055
     - 448368
     - 1.61×
   * - resolve_mixed_lifetimes
     - 1068162
     - 236157
     - 4.52×
   * - resolve_scoped
     - 1426427
     - 604451
     - 2.36×
   * - resolve_singleton
     - 2703307
     - 3266299
     - 0.83×
   * - resolve_transient
     - 1930579
     - 1974379
     - 0.98×
   * - resolve_wide_transient_graph
     - 1057927
     - 434771
     - 2.43×

Summary (computed from the table above):

- Up to **7.02×** faster
- Median speedup: **2.40×**
- Mean speedup: **2.85×**

These results vary by scenario. Some scenarios may be slower than dishka (speedup < 1×), so avoid assuming a fixed
“always N×” speedup for every workload.
