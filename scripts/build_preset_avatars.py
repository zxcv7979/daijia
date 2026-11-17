"""生成三个可随仓库分发的原创 GLB 预设。不下载外部模型。"""

from __future__ import annotations

import json
from pathlib import Path

from src.avatar.glb import write_character_glb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "avatars" / "presets"


def main() -> None:
    specs = [
        ("yuan.glb", "圆圆", (232, 188, 154), (1.0, 1.0, 1.0)),
        ("qing.glb", "青青", (196, 164, 140), (0.92, 1.08, 0.92)),
        ("he.glb", "禾禾", (150, 108, 82), (1.08, 0.94, 1.02)),
    ]
    library = []
    for filename, name, tint, scale in specs:
        path = OUT / filename
        write_character_glb(path, name=name, tint=tint, scale=scale)
        library.append(
            {
                "file": f"presets/{filename}",
                "name": name,
                "bytes": path.stat().st_size,
                "license": "本仓库原创参数化网格，可随仓库使用和修改",
                "source": "scripts/build_preset_avatars.py",
            }
        )
        print(f"{filename} {path.stat().st_size} bytes")
    (ROOT / "data" / "avatars" / "library.json").write_text(
        json.dumps(library, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
