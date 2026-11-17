"""只探测本机有没有 NVIDIA GPU。没有时绝不假装跑过三维重建模型。"""

from __future__ import annotations

import shutil
import subprocess


def describe_gpu() -> dict[str, object]:
    present = _nvidia_smi_ok()
    return {
        "cuda": present,
        "cloud_api": False,
        "reconstruction_ran": False,
        "mode": "gpu-local" if present else "parametric-fallback",
        "note": (
            "检测到 NVIDIA GPU。是否真正跑本地重建仍取决于使用方自己安装的工具，本仓库默认不下载模型。"
            if present
            else "没有检测到 NVIDIA GPU。照片任务使用参数化头回退，不是 InstantMesh、TripoSR 或 Hunyuan3D。60 秒 GPU 出 GLB 为待实机验收。"
        ),
    }


def _nvidia_smi_ok() -> bool:
    binary = shutil.which("nvidia-smi")
    if not binary:
        return False
    try:
        result = subprocess.run([binary, "-L"], check=False, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "GPU" in (result.stdout or "")
