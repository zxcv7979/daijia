"""1000 条/秒模拟源。丢弃必须符合 drop_oldest，并带告警。"""

from __future__ import annotations

import asyncio

from src.adapters.loadtest import run_mock_load


def test_mock_source_one_thousand_per_second(project):
    result = asyncio.run(run_mock_load(project, count=1000, window_sec=1.0))
    governor = result["governor"]
    assert governor["consistent"] is True
    assert governor["dropped_silent"] == 0
    assert result["dropped_pipeline"] == 0
    assert result["published"] == 1000 - governor["duplicates"] - governor["dropped_oldest"]
    if governor["dropped_oldest"]:
        assert governor["alert_count"] >= 1
        assert governor["alerts"]
    else:
        assert governor["alert_count"] == 0
    assert result["e2e_ms"]["n"] == result["published"]
    print(
        "LOAD "
        f"p50={result['e2e_ms']['p50']:.3f} "
        f"p95={result['e2e_ms']['p95']:.3f} "
        f"p99={result['e2e_ms']['p99']:.3f} "
        f"peak={result['memory_peak_bytes']} "
        f"dropped_oldest={governor['dropped_oldest']} "
        f"elapsed={result['elapsed_sec']}"
    )
