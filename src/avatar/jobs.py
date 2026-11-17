"""照片任务：同意、质检、加密保存、参数化回退、人工复核。"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from src.adapters.crypto import decrypt, derive_key, encrypt
from src.avatar.glb import write_likeness_glb
from src.avatar.gpu import describe_gpu
from src.avatar.qa import check_photo_bytes, texture_png
from src.store import Store

PRESETS = (
    {
        "avatar_id": "preset-yuan",
        "name": "圆圆",
        "file": "presets/yuan.glb",
        "kind": "preset",
        "license": "本仓库原创参数化网格",
        "source": "scripts/build_preset_avatars.py",
    },
    {
        "avatar_id": "preset-qing",
        "name": "青青",
        "file": "presets/qing.glb",
        "kind": "preset",
        "license": "本仓库原创参数化网格",
        "source": "scripts/build_preset_avatars.py",
    },
    {
        "avatar_id": "preset-he",
        "name": "禾禾",
        "file": "presets/he.glb",
        "kind": "preset",
        "license": "本仓库原创参数化网格",
        "source": "scripts/build_preset_avatars.py",
    },
)


class AvatarError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class AvatarLibrary:
    def __init__(self, root: Path, store: Store, salt: str, *, retention_days: int = 7, seed: int = 42) -> None:
        self.root = root
        self.store = store
        self.salt = salt
        self.retention_days = retention_days
        self.seed = seed
        self.avatar_dir = root / "data" / "avatars"
        self.derived = self.avatar_dir / "derived"
        self.derived.mkdir(parents=True, exist_ok=True)

    def list_assets(self) -> list[dict]:
        rows = {item["avatar_id"]: item for item in self.store.list_avatars()}
        assets = []
        for preset in PRESETS:
            path = self.avatar_dir / preset["file"]
            assets.append({**preset, "ready": path.is_file(), "bytes": path.stat().st_size if path.is_file() else 0})
        assets.extend(rows.values())
        return assets

    def file_for(self, avatar_id: str) -> Path | None:
        for preset in PRESETS:
            if preset["avatar_id"] == avatar_id:
                path = self.avatar_dir / preset["file"]
                return path if path.is_file() else None
        row = self.store.get_avatar(avatar_id)
        if not row or not row.get("glb_rel"):
            return None
        path = self.avatar_dir / str(row["glb_rel"])
        return path if path.is_file() else None

    def submit_photos(
        self,
        photos: list[tuple[str, bytes]],
        *,
        consent: bool,
        subject_is_minor: bool,
        sensitive: bool,
        avatar_id: str | None = None,
        preset_id: str | None = None,
    ) -> dict:
        if not consent:
            raise AvatarError(400, "需要勾选同意后才能上传照片")
        blocked = sensitive_block(subject_is_minor=subject_is_minor, sensitive=sensitive)
        if blocked:
            raise AvatarError(400, blocked)
        if not 1 <= len(photos) <= 5:
            raise AvatarError(400, "请上传 1 到 5 张正脸照片")
        if preset_id and preset_id not in {item["avatar_id"] for item in PRESETS}:
            raise AvatarError(400, "未知的预设角色")
        reasons: list[str] = []
        for name, payload in photos:
            found = check_photo_bytes(payload)
            reasons.extend(f"{name}：{item}" for item in found)
        avatar = avatar_id or f"ava-{uuid.uuid4().hex[:10]}"
        job_id = uuid.uuid4().hex
        now = time.time()
        status = "failed" if reasons else "review"
        generator = "parametric-fallback"
        gpu = describe_gpu()
        glb_rel = ""
        if not reasons:
            texture = texture_png(photos[0][1])
            glb_rel = f"derived/{avatar}.glb"
            write_likeness_glb(self.avatar_dir / glb_rel, seed=self.seed, texture=texture)
        key = derive_key(self.salt)
        retain = now + self.retention_days * 86400
        photo_ids = []
        for name, payload in photos:
            photo_id = uuid.uuid4().hex
            token = encrypt(key, payload)
            self.store.save_avatar_photo(photo_id, job_id, name, token, now, retain)
            photo_ids.append(photo_id)
        self.store.save_avatar_job(
            {
                "job_id": job_id,
                "avatar_id": avatar,
                "preset_id": preset_id or "",
                "status": status,
                "seed": self.seed,
                "reasons": reasons,
                "consent": True,
                "generator": generator,
                "gpu": gpu,
                "glb_rel": glb_rel,
                "created_at": now,
                "photo_ids": photo_ids,
            }
        )
        if not reasons:
            self.store.save_avatar(
                {
                    "avatar_id": avatar,
                    "kind": "likeness",
                    "preset_id": preset_id or "",
                    "job_id": job_id,
                    "name": avatar,
                    "glb_rel": glb_rel,
                    "approved": False,
                    "created_at": now,
                }
            )
        return self.store.get_avatar_job(job_id)

    def approve(self, job_id: str) -> dict:
        job = self._job(job_id)
        if job["status"] != "review":
            raise AvatarError(400, "只有待复核的任务可以通过")
        self.store.set_avatar_job_status(job_id, "approved")
        self.store.set_avatar_approved(job["avatar_id"], True)
        return self.store.get_avatar_job(job_id)

    def regenerate(self, job_id: str) -> dict:
        job = self._job(job_id)
        if job["status"] not in {"review", "approved", "failed"}:
            raise AvatarError(400, "这个任务不能重做")
        if job["status"] == "failed":
            raise AvatarError(400, "质检没过，请换照片后重新上传")
        photos = self.store.list_avatar_photos(job_id)
        if not photos:
            raise AvatarError(400, "原照片已删除，请重新上传")
        key = derive_key(self.salt)
        first = decrypt(key, photos[0]["blob"])
        seed = int(job["seed"]) + 1
        glb_rel = job["glb_rel"] or f"derived/{job['avatar_id']}.glb"
        write_likeness_glb(self.avatar_dir / glb_rel, seed=seed, texture=texture_png(first))
        self.store.update_avatar_job_result(job_id, status="review", seed=seed, glb_rel=glb_rel)
        self.store.set_avatar_approved(job["avatar_id"], False)
        return self.store.get_avatar_job(job_id)

    def delete_avatar(self, avatar_id: str) -> dict:
        if avatar_id.startswith("preset-"):
            raise AvatarError(400, "预设角色不能删除")
        jobs = self.store.jobs_for_avatar(avatar_id)
        removed_photos = 0
        for job in jobs:
            removed_photos += self.store.delete_avatar_photos(job["job_id"])
            if job.get("glb_rel"):
                path = self.avatar_dir / str(job["glb_rel"])
                if path.is_file():
                    path.unlink()
            self.store.delete_avatar_job(job["job_id"])
        self.store.delete_avatar(avatar_id)
        return {"avatar_id": avatar_id, "deleted_photos": removed_photos, "deleted_jobs": len(jobs)}

    def _job(self, job_id: str) -> dict:
        job = self.store.get_avatar_job(job_id)
        if job is None:
            raise AvatarError(404, "找不到这个任务")
        return job


def sensitive_block(*, subject_is_minor: bool, sensitive: bool) -> str | None:
    if subject_is_minor or sensitive:
        return "不接收未成年人或敏感主体照片，请改用预设角色"
    return None
