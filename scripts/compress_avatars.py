"""可选：用 gltf-transform 做 Draco / KTX2。默认预设已经很小，不跑这步也能加载。

    npx --yes @gltf-transform/cli@4 optimize data/avatars/presets/yuan.glb data/avatars/presets/yuan.draco.glb --compress draco --texture-compress ktx2

云环境和没有编码器的机器跳过即可。加载目标仍是 2 秒以内，未压缩的预设通常远小于这个时间。
本脚本不会访问照片，也不会调用重建模型。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRESETS = ROOT / "data" / "avatars" / "presets"


def main() -> None:
    if shutil.which("npx") is None:
        print("没有 npx，跳过 Draco/KTX2。预设 GLB 仍可直接加载。")
        return
    for source in sorted(PRESETS.glob("*.glb")):
        if source.name.endswith(".draco.glb"):
            continue
        target = source.with_name(source.stem + ".draco.glb")
        command = [
            "npx",
            "--yes",
            "@gltf-transform/cli@4",
            "optimize",
            str(source),
            str(target),
            "--compress",
            "draco",
            "--texture-compress",
            "ktx2",
        ]
        print(" ".join(command))
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            sys.exit("压缩失败。未压缩的 GLB 仍然可用。")


if __name__ == "__main__":
    main()
