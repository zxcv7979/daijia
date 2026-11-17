"""测试用的临时项目目录，避免改到仓库里的配置和数据库。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    for name in ("default.yaml", "mappings.yaml", "compliance.yaml"):
        (config / name).write_text((ROOT / "config" / name).read_text(encoding="utf-8"), encoding="utf-8")
    samples = tmp_path / "data" / "samples"
    samples.mkdir(parents=True)
    for sample in (ROOT / "data" / "samples").glob("*.jsonl"):
        (samples / sample.name).write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(project: Path):
    from src.api.app import create_app

    app = create_app(project)
    with TestClient(app) as test_client:
        yield test_client
