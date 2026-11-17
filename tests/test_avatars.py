"""照片质检、同意与删除、任务状态，以及预设 GLB。"""

from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from src.avatar.blendshapes import ARKIT_52, weights_for_emotion
from src.avatar.glb import read_glb_json
from src.avatar.gpu import describe_gpu
from src.avatar.qa import check_photo
from src.avatar.switch import switch_plan


def _face(width: int = 180, height: int = 220, shift: int = 0, blobs: int = 1, flat: bool = False, dark: bool = False) -> bytes:
    color = (20, 16, 14) if dark else (90, 120, 150)
    image = Image.new("RGB", (width, height), color if not flat else (180, 180, 180))
    draw = ImageDraw.Draw(image)
    if not flat and not dark:
        for index in range(blobs):
            cx = width // 2 + shift + (index - (blobs - 1) / 2) * 120
            draw.ellipse((cx - 40, 50, cx + 40, 160), fill=(214, 164, 132))
            draw.ellipse((cx - 18, 80, cx - 8, 92), fill=(40, 30, 24))
            draw.ellipse((cx + 8, 80, cx + 18, 92), fill=(40, 30, 24))
            draw.arc((cx - 16, 110, cx + 16, 136), 10, 170, fill=(120, 60, 60), width=2)
        if not flat:
            for y in range(height):
                for x in range(0, width, 3):
                    pixel = image.getpixel((x, y))
                    image.putpixel((x, y), tuple(min(255, channel + ((x * y) % 7)) for channel in pixel))
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_qa_reasons_are_specific():
    assert "照片太小，看不清正脸" in check_photo(Image.open(BytesIO(_face(40, 40))))
    assert "光线过暗" in check_photo(Image.new("RGB", (180, 220), (10, 10, 10)))
    assert "光线过亮" in check_photo(Image.new("RGB", (180, 220), (250, 250, 250)))
    blurry = check_photo(Image.new("RGB", (180, 220), (180, 150, 130)))
    assert "画面太糊" in blurry
    side = check_photo(Image.open(BytesIO(_face(shift=-70, width=240))))
    assert "未检测到正脸" in side
    many = check_photo(Image.open(BytesIO(_face(blobs=2, width=360))))
    assert "检测到多张脸" in many
    good = check_photo(Image.open(BytesIO(_face())))
    assert good == []


def test_blendshape_map_covers_arkit_and_joy():
    assert len(ARKIT_52) == 52
    joy = weights_for_emotion("joy", 1)
    assert set(joy) == set(ARKIT_52)
    assert joy["mouthSmileLeft"] > 0.5
    awe = weights_for_emotion("awe", 1, blink=1, lip=0.2)
    assert awe["jawOpen"] >= 0.7
    assert awe["eyeBlinkLeft"] == 1


def test_switch_keeps_last_frame_until_loaded():
    assert switch_plan(current="preset-yuan", incoming="preset-qing", loaded=False) == "keep-current"
    assert switch_plan(current="preset-yuan", incoming="preset-qing", loaded=True) == "crossfade"
    assert switch_plan(current="preset-yuan", incoming="preset-yuan", loaded=True) == "same"


def test_preset_glbs_exist_and_name_all_blendshapes():
    root = Path("data/avatars/presets")
    for name in ("yuan.glb", "qing.glb", "he.glb"):
        path = root / name
        assert path.is_file()
        started = time.perf_counter()
        document = read_glb_json(path)
        assert time.perf_counter() - started < 2
        assert path.stat().st_size < 2_000_000
        assert document["meshes"][0]["extras"]["targetNames"] == list(ARKIT_52)


def test_switch_preset_without_dropping_current(client):
    switched = client.post("/api/avatars/active", data={"avatar_id": "preset-qing"})
    assert switched.status_code == 200
    assert switched.json()["plan"] == "crossfade"
    missing = client.post("/api/avatars/active", data={"avatar_id": "missing-head"})
    assert missing.status_code == 404
    assert "上一个角色" in missing.json()["detail"]
    assert client.get("/api/avatars").json()["active"] == "preset-qing"


def test_photo_job_review_reuse_and_delete(client):
    denied = client.post("/api/avatars/jobs", data={"consent": "false"}, files=[("photos", ("a.png", _face(), "image/png"))])
    assert denied.status_code == 400
    assert "同意" in denied.json()["detail"]
    minor = client.post(
        "/api/avatars/jobs",
        data={"consent": "true", "subject_is_minor": "true"},
        files=[("photos", ("a.png", _face(), "image/png"))],
    )
    assert minor.status_code == 400
    assert "未成年人" in minor.json()["detail"]
    created = client.post(
        "/api/avatars/jobs",
        data={"consent": "true", "preset_id": "preset-yuan", "avatar_id": "ava-demo"},
        files=[("photos", ("face.png", _face(), "image/png"))],
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "review"
    assert body["generator"] == "parametric-fallback"
    assert body["gpu"]["reconstruction_ran"] is False
    assert body["gpu"]["cloud_api"] is False
    assert "face.png" not in created.text or "PNG" not in created.text
    assert b"\x89PNG" not in created.content
    avatar_id = body["avatar_id"]
    assert avatar_id == "ava-demo"
    again = client.post(
        "/api/avatars/jobs",
        data={"consent": "true", "avatar_id": avatar_id},
        files=[("photos", ("face2.png", _face(), "image/png"))],
    )
    assert again.json()["avatar_id"] == avatar_id
    approved = client.post(f"/api/avatars/jobs/{body['job_id']}/approve")
    assert approved.json()["status"] == "approved"
    redone = client.post(f"/api/avatars/jobs/{body['job_id']}/regenerate")
    assert redone.json()["status"] == "review"
    assert redone.json()["seed"] == body["seed"] + 1
    removed = client.delete(f"/api/avatars/{avatar_id}")
    assert removed.status_code == 200
    assert removed.json()["deleted_photos"] >= 1
    assert client.get(f"/api/avatars/jobs/{body['job_id']}").status_code == 404


def test_gpu_probe_does_not_claim_reconstruction():
    info = describe_gpu()
    assert info["reconstruction_ran"] is False
    assert info["cloud_api"] is False
    if not info["cuda"]:
        assert info["mode"] == "parametric-fallback"
        assert "待实机验收" in str(info["note"])
