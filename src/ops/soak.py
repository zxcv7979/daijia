"""虚拟演出浸泡。事件、打印队列和角色回退都在进程内，不连接平台或打印机。"""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import Any

from src.models import AvatarType, PrintStyle
from src.ops.alerts import adapter_problem, raise_alert
from src.ops.degrade import PRESET_FALLBACK, canned_frame
from src.ops.metrics import budget_breaches, growth, growth_ratio, sample_metrics
from src.ops.retention import cleanup_expired_photos
from src.runtime import Context

RSS_BUDGET_KB = 256 * 1024
FD_BUDGET = 40


def stage_root(source: Path, dest: Path) -> None:
    config = dest / "config"
    config.mkdir(parents=True)
    for name in ("default.yaml", "mappings.yaml", "compliance.yaml"):
        shutil.copy(source / "config" / name, config / name)


async def run_soak(source: Path, dest: Path, *, duration_sec: float, interval_sec: float = 0.5) -> dict[str, Any]:
    stage_root(source, dest)
    ctx = Context(dest)
    samples: list[dict[str, Any]] = []
    canned_steps = 0
    noted_fallback = False
    noted_drop = False
    noted_adapter = False
    started = time.monotonic()
    await ctx.startup()
    try:
        await ctx.sources.start("mock", real_allowed=False)
        while time.monotonic() - started < duration_sec:
            index = len(samples)
            await ctx.ingest(
                {
                    "adapter": "sim",
                    "source_msg_id": f"soak-{index}",
                    "type": "danmaku",
                    "user_id": f"viewer-{index % 6}",
                    "nickname": "观众",
                    "text": "好看",
                }
            )
            if not ctx.printer.queue_ids() and index % 3 == 0:
                job = ctx.printer.create(
                    style=PrintStyle.cartoon,
                    avatar_type=AvatarType.stylized,
                    duration_sec=1.0,
                    avatar_id=PRESET_FALLBACK,
                )
                ctx.audit.record("print_trigger", {"job_id": job.job_id, "source": "soak"})
            if not noted_fallback:
                ctx.audit.record(
                    "avatar_fallback",
                    {"preset": PRESET_FALLBACK, "reason": "浸泡使用预设，不上传照片"},
                )
                noted_fallback = True
            canned_frame(canned_steps)
            canned_steps += 1
            problem = adapter_problem(ctx.sources.health("mock"))
            if problem and not noted_adapter:
                raise_alert(ctx.audit, "adapter_unhealthy", {"detail": problem})
                noted_adapter = True
            if ctx.stats.dropped and not noted_drop:
                raise_alert(ctx.audit, "drop", {"dropped": ctx.stats.dropped})
                noted_drop = True
            samples.append(sample_metrics())
            await asyncio.sleep(interval_sec)
        retention = cleanup_expired_photos(
            ctx.store,
            now=time.time(),
            retention_days=ctx.settings.retention_days(),
            dry_run=True,
        )
    finally:
        await ctx.shutdown()
    breaches = budget_breaches(samples, rss_kb=RSS_BUDGET_KB, fds=FD_BUDGET)
    ratio = growth_ratio(samples)
    full_8h = duration_sec >= 8 * 3600 - 1
    if full_8h and ratio is not None and ratio >= 0.20:
        breaches.append("rss_ratio")
    return {
        "duration_sec": round(time.monotonic() - started, 3),
        "samples": len(samples),
        "growth": growth(samples),
        "rss_growth_ratio": ratio,
        "gpu_seen": any(item.get("gpu") for item in samples),
        "breaches": breaches,
        "canned_steps": canned_steps,
        "retention": retention,
        "ok": not breaches,
        "full_8h": full_8h,
        "webgl_context_loss": "待实机验收",
    }
