"""非法 YAML 被拒绝，进程和旧映射都保持原样。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.settings import ConfigError, NormalizeCfg, Settings


def test_window_must_stay_200ms():
    with pytest.raises(ValidationError):
        NormalizeCfg(danmaku_aggregate_window_ms=2000)


def test_invalid_mapping_file_does_not_replace_memory(project):
    settings = Settings(project)
    previous = settings.mappings_model.tiers["L0"].emotion.value
    path = project / "config" / "mappings.yaml"
    path.write_text("tiers: [\n", encoding="utf-8")
    changed = settings.poll_once()
    assert changed == []
    assert settings.last_error
    assert settings.mappings_model.tiers["L0"].emotion.value == previous
    with pytest.raises(ConfigError):
        settings.apply_mappings_text("hello: [")
    assert settings.mappings_model.tiers["L0"].emotion.value == previous


def test_invalid_official_adapter_is_rejected(project):
    settings = Settings(project)
    path = project / "config" / "default.yaml"
    text = path.read_text(encoding="utf-8").replace("mode: stub", "mode: live", 1)
    path.write_text(text, encoding="utf-8")
    settings.poll_once()
    assert settings.last_error
    assert settings.default_model.adapters.official.enabled is False
    assert settings.default_model.adapters.official.mode == "stub"


def test_api_rejects_bad_yaml_and_keeps_serving(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    bad = client.put("/api/mappings", json={"yaml": "::: 不是合法映射"})
    assert bad.status_code == 400
    assert client.get("/api/health").status_code == 200
    still = client.post("/api/trigger", json={"level": "L0"})
    assert still.status_code == 200
    assert still.json()["emotion"]["emotion"] == "ambient"
    current = client.get("/api/mappings").json()["yaml"]
    updated = current.replace("emotion: ambient", "emotion: tender", 1)
    ok = client.put("/api/mappings", json={"yaml": updated})
    assert ok.status_code == 200
    changed = client.post("/api/trigger", json={"level": "L0"})
    assert changed.status_code == 200
    assert changed.json()["emotion"]["emotion"] == "tender"
    assert changed.json()["fx_cue"]["level"] == "L0"
    blocked = client.put(
        "/api/mappings",
        json={
            "yaml": """
tiers:
  L0: {priority: 0, emotion: ambient, intensity: 0.2, fx: a, triggers: [{type: like}]}
  L1: {priority: 1, emotion: ambient, intensity: 0.2, fx: b, triggers: [{type: danmaku}]}
  L2: {priority: 3, emotion: joy, intensity: 0.5, fx: c, triggers: [{type: follow}]}
  L3: {priority: 5, emotion: hype, intensity: 0.7, fx: d, triggers: [{type: gift, price_min: 10, price_max: 99}]}
  L4: {priority: 8, emotion: awe, intensity: 0.9, fx: e, triggers: [{type: gift, price_min: 100}]}
"""
        },
    )
    assert blocked.status_code == 400
    assert client.post("/api/trigger", json={"level": "L0"}).json()["emotion"]["emotion"] == "tender"
