from __future__ import annotations

import json

from tests.benchmarks.rodi_comparison import BenchmarkResult, write_outputs


def test_write_outputs_creates_markdown_and_json_files(tmp_path) -> None:
    results = [
        BenchmarkResult(
            case="open_scope",
            provider="factory",
            lifetime="singleton",
            diwire_concurrency_safe="enabled",
            diwire_us_per_op=1.25,
            rodi_us_per_op=1.75,
            ratio_rodi_over_diwire=1.4,
            winner="DIWire",
        ),
    ]
    markdown_path = tmp_path / "rodi-comparison.md"
    json_path = tmp_path / "rodi-comparison.json"

    write_outputs(
        results,
        output_markdown=markdown_path,
        output_json=json_path,
    )

    markdown = markdown_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert (
        "| Scenario | Resolves/Scope | Provider Registration | Lifetime | DIWire Concurrency Safe | "
        "DIWire (us/op) | Rodi (us/op) | Rodi/DIWire | Winner |" in markdown
    )
    assert (
        "| Scope open/close only | 0 | Factory provider | singleton | enabled | "
        "1.250 | 1.750 | 1.400 | DIWire |"
    ) in markdown
    assert payload[0]["winner"] == "DIWire"
