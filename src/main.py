"""演示进程入口。读取 config/default.yaml 的监听地址。"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from src.api.app import create_app


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


_configure_logging()
app = create_app()


def main() -> None:
    import uvicorn

    root = Path(__file__).resolve().parents[1]
    raw = yaml.safe_load((root / "config" / "default.yaml").read_text(encoding="utf-8"))
    host = raw["server"]["host"]
    port = int(raw["server"]["port"])
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
