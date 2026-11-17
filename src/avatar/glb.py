"""写出带 ARKit 形变名的小型 GLB。网格是本仓库原创的，不依赖外部模型。"""

from __future__ import annotations

import json
import math
import struct
import zlib
from pathlib import Path

from src.avatar.blendshapes import ARKIT_52


def write_character_glb(path: Path, *, name: str, tint: tuple[int, int, int], scale: tuple[float, float, float]) -> None:
    positions, normals, uvs, indices = _sphere()
    count = len(positions)
    targets = [_morph(positions, shape, scale) for shape in ARKIT_52]
    png = _png(16, 16, (*tint, 255))
    blob = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []

    def push(data: bytes, *, target: int | None = None) -> int:
        while len(blob) % 4:
            blob.append(0)
        start = len(blob)
        blob.extend(data)
        view = {"buffer": 0, "byteOffset": start, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        views.append(view)
        return len(views) - 1

    position_bytes = _vec3(positions)
    normal_bytes = _vec3(normals)
    uv_bytes = _vec2(uvs)
    index_bytes = struct.pack("<" + "H" * len(indices), *indices)
    pos_view = push(position_bytes, target=34962)
    normal_view = push(normal_bytes, target=34962)
    uv_view = push(uv_bytes, target=34962)
    index_view = push(index_bytes, target=34963)
    accessors.extend(
        [
            _accessor(pos_view, count, "VEC3", 5126, _minmax(positions)),
            _accessor(normal_view, count, "VEC3", 5126, None),
            _accessor(uv_view, count, "VEC2", 5126, None),
            _accessor(index_view, len(indices), "SCALAR", 5123, None),
        ]
    )
    target_refs = []
    for morph in targets:
        view = push(_vec3(morph), target=34962)
        accessors.append(_accessor(view, count, "VEC3", 5126, _minmax(morph)))
        target_refs.append({"POSITION": len(accessors) - 1})
    image_view = push(png)
    document = {
        "asset": {
            "version": "2.0",
            "generator": "live-show-preset",
            "extras": {
                "license": "本仓库原创参数化网格，可随仓库使用和修改",
                "source": "scripts/build_preset_avatars.py",
                "name": name,
            },
        },
        "buffers": [{"byteLength": 0}],
        "bufferViews": views,
        "accessors": accessors,
        "images": [{"bufferView": image_view, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "materials": [
            {
                "name": name,
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.7,
                },
            }
        ],
        "meshes": [
            {
                "name": name,
                "weights": [0.0] * len(ARKIT_52),
                "extras": {"targetNames": list(ARKIT_52)},
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                        "indices": 3,
                        "material": 0,
                        "targets": target_refs,
                    }
                ],
            }
        ],
        "nodes": [{"name": name, "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    document["buffers"][0]["byteLength"] = len(blob)
    _write(path, document, bytes(blob))


def write_likeness_glb(path: Path, *, seed: int, texture: bytes) -> None:
    """无显卡时的参数化头。extras 里写明不是 GPU 重建。"""

    positions, normals, uvs, indices = _sphere()
    count = len(positions)
    # 用种子只影响一个可复现的轻微缩放，不假装是神经重建。
    scale = (0.9 + (seed % 7) * 0.01, 1.0, 0.9)
    targets = [_morph(positions, shape, scale) for shape in ARKIT_52]
    blob = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []

    def push(data: bytes, *, target: int | None = None) -> int:
        while len(blob) % 4:
            blob.append(0)
        start = len(blob)
        blob.extend(data)
        view = {"buffer": 0, "byteOffset": start, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        views.append(view)
        return len(views) - 1

    pos_view = push(_vec3([(x * scale[0], y * scale[1], z * scale[2]) for x, y, z in positions]), target=34962)
    normal_view = push(_vec3(normals), target=34962)
    uv_view = push(_vec2(uvs), target=34962)
    index_view = push(struct.pack("<" + "H" * len(indices), *indices), target=34963)
    accessors.extend(
        [
            _accessor(pos_view, count, "VEC3", 5126, None),
            _accessor(normal_view, count, "VEC3", 5126, None),
            _accessor(uv_view, count, "VEC2", 5126, None),
            _accessor(index_view, len(indices), "SCALAR", 5123, None),
        ]
    )
    target_refs = []
    for morph in targets:
        view = push(_vec3(morph), target=34962)
        accessors.append(_accessor(view, count, "VEC3", 5126, None))
        target_refs.append({"POSITION": len(accessors) - 1})
    image_view = push(texture)
    document = {
        "asset": {
            "version": "2.0",
            "generator": "live-show-parametric-fallback",
            "extras": {
                "generator": "parametric-fallback",
                "gpu_reconstruction": False,
                "seed": seed,
                "label": "无 NVIDIA GPU 时的参数化头，不是 InstantMesh、TripoSR 或 Hunyuan3D",
            },
        },
        "buffers": [{"byteLength": 0}],
        "bufferViews": views,
        "accessors": accessors,
        "images": [{"bufferView": image_view, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "materials": [
            {
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.65,
                }
            }
        ],
        "meshes": [
            {
                "name": "likeness",
                "weights": [0.0] * len(ARKIT_52),
                "extras": {"targetNames": list(ARKIT_52)},
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                        "indices": 3,
                        "material": 0,
                        "targets": target_refs,
                    }
                ],
            }
        ],
        "nodes": [{"name": "likeness", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    document["buffers"][0]["byteLength"] = len(blob)
    _write(path, document, bytes(blob))


def read_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    magic, version, _length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2:
        raise ValueError("不是 GLB 2.0")
    chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != 0x4E4F534A:
        raise ValueError("缺少 JSON 块")
    return json.loads(data[20 : 20 + chunk_length].rstrip(b" \x00"))


def _write(path: Path, document: dict, blob: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_json = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    raw_json += b" " * ((4 - len(raw_json) % 4) % 4)
    bin_data = blob + b"\x00" * ((4 - len(blob) % 4) % 4)
    total = 12 + 8 + len(raw_json) + 8 + len(bin_data)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(raw_json), 0x4E4F534A)
    out += raw_json
    out += struct.pack("<II", len(bin_data), 0x004E4942)
    out += bin_data
    path.write_bytes(out)


def _sphere(seg: int = 8, rings: int = 6) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[float, float]], list[int]]:
    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    for y in range(rings + 1):
        phi = y / rings * math.pi
        for x in range(seg + 1):
            theta = x / seg * math.tau
            nx = math.sin(phi) * math.cos(theta)
            ny = math.cos(phi)
            nz = math.sin(phi) * math.sin(theta)
            positions.append((nx * 0.72, ny * 0.8, nz * 0.72))
            normals.append((nx, ny, nz))
            uvs.append((x / seg, 1 - y / rings))
    indices: list[int] = []
    for y in range(rings):
        for x in range(seg):
            a = y * (seg + 1) + x
            b = a + seg + 1
            indices.extend((a, b, a + 1, b, b + 1, a + 1))
    return positions, normals, uvs, indices


def _morph(positions: list[tuple[float, float, float]], shape: str, scale: tuple[float, float, float]) -> list[tuple[float, float, float]]:
    deltas = [(0.0, 0.0, 0.0)] * len(positions)
    edited = list(deltas)
    for index, (x, y, z) in enumerate(positions):
        dx = dy = dz = 0.0
        if shape == "jawOpen" and y < -0.05:
            dy = -0.16 * scale[1]
        elif shape in {"mouthSmileLeft", "mouthSmileRight"} and y < 0.05 and abs(x) > 0.15:
            dx = 0.05 * (1 if x > 0 else -1)
            dy = 0.04
        elif shape in {"eyeBlinkLeft", "eyeBlinkRight"} and y > 0.25 and z > 0.2:
            dy = -0.05 if (shape.endswith("Left") and x < 0) or (shape.endswith("Right") and x > 0) else 0.0
        elif shape in {"eyeWideLeft", "eyeWideRight"} and y > 0.2 and z > 0.15:
            dy = 0.04
        elif shape == "browInnerUp" and y > 0.45:
            dy = 0.06
        elif shape in {"browDownLeft", "browDownRight"} and y > 0.4:
            dy = -0.05
        elif shape in {"mouthFrownLeft", "mouthFrownRight"} and y < 0 and abs(x) > 0.1:
            dy = -0.04
        edited[index] = (dx, dy, dz)
    return edited


def _vec3(values: list[tuple[float, float, float]]) -> bytes:
    return b"".join(struct.pack("<fff", x, y, z) for x, y, z in values)


def _vec2(values: list[tuple[float, float]]) -> bytes:
    return b"".join(struct.pack("<ff", x, y) for x, y in values)


def _minmax(values: list[tuple[float, float, float]]) -> dict:
    xs = [item[0] for item in values]
    ys = [item[1] for item in values]
    zs = [item[2] for item in values]
    return {"min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]}


def _accessor(view: int, count: int, kind: str, component: int, bounds: dict | None) -> dict:
    item = {"bufferView": view, "componentType": component, "count": count, "type": kind}
    if bounds:
        item.update(bounds)
    return item


def _png(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    r, g, b, _a = rgba
    raw = b"".join(b"\x00" + bytes((r, g, b)) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
