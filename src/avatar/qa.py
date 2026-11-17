"""上传照片的本地质量检查。不把图片发到任何外部服务。"""

from __future__ import annotations

from io import BytesIO

from PIL import Image


def check_photo(image: Image.Image) -> list[str]:
    """返回中文失败原因。空列表表示可以通过。"""

    reasons: list[str] = []
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 96 or height < 96:
        reasons.append("照片太小，看不清正脸")
        return reasons
    gray = _values(rgb.convert("L"))
    mean = sum(gray) / len(gray)
    if mean < 45:
        reasons.append("光线过暗")
    if mean > 225:
        reasons.append("光线过亮")
    if _sharpness(gray, width, height) < 6:
        reasons.append("画面太糊")
    if _face_offset(rgb) > 0.12:
        reasons.append("未检测到正脸")
    faces = _skin_blobs(rgb)
    if faces == 0:
        reasons.append("没有人脸")
    elif faces > 1:
        reasons.append("检测到多张脸")
    if _occluded(gray, width, height):
        reasons.append("脸部被遮挡")
    return reasons


def check_photo_bytes(payload: bytes) -> list[str]:
    try:
        image = Image.open(BytesIO(payload))
        image.load()
    except Exception:
        return ["打不开这张照片，请换一张正脸重试"]
    return check_photo(image)


def texture_png(payload: bytes, size: int = 32) -> bytes:
    image = Image.open(BytesIO(payload)).convert("RGB")
    crop = _center_square(image)
    crop = crop.resize((size, size))
    out = BytesIO()
    crop.save(out, format="PNG")
    return out.getvalue()


def _sharpness(gray: list[int], width: int, height: int) -> float:
    total = 0.0
    count = 0
    for y in range(1, height - 1, 2):
        row = y * width
        for x in range(1, width - 1, 2):
            center = gray[row + x]
            total += abs(center * 4 - gray[row + x - 1] - gray[row + x + 1] - gray[row - width + x] - gray[row + width + x])
            count += 1
    return total / max(1, count)


def _face_offset(image: Image.Image) -> float:
    """肤色重心离画面中心有多远。0 是正中，越大越不像正脸。没有肤色时返回 0，交给「没有人脸」。"""

    small = image.resize((48, 48))
    xs = []
    for index, (red, green, blue) in enumerate(_values(small)):
        if red > 95 and green > 40 and blue > 20 and red > green and red > blue and abs(red - green) > 15:
            xs.append(index % 48)
    if len(xs) < 18:
        return 0.0
    center = sum(xs) / len(xs)
    return abs(center - 23.5) / 48


def _occluded(gray: list[int], width: int, height: int) -> bool:
    x0, x1 = int(width * 0.35), int(width * 0.65)
    y0, y1 = int(height * 0.3), int(height * 0.7)
    center: list[int] = []
    for y in range(y0, y1):
        row = y * width
        center.extend(gray[row + x0 : row + x1])
    if not center:
        return False
    mean = sum(center) / len(center)
    vary = sum(abs(item - mean) for item in center) / len(center)
    return mean < 35 and vary < 8


def _skin_blobs(image: Image.Image) -> int:
    small = image.resize((48, 48))
    pixels = _values(small)
    mask = []
    for red, green, blue in pixels:
        skin = red > 95 and green > 40 and blue > 20 and red > green and red > blue and abs(red - green) > 15
        mask.append(skin)
    seen = [False] * len(mask)
    blobs = 0
    for index, on in enumerate(mask):
        if not on or seen[index]:
            continue
        stack = [index]
        seen[index] = True
        area = 0
        while stack:
            current = stack.pop()
            area += 1
            x, y = current % 48, current // 48
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < 48 and 0 <= ny < 48:
                    nxt = ny * 48 + nx
                    if mask[nxt] and not seen[nxt]:
                        seen[nxt] = True
                        stack.append(nxt)
        if area >= 18:
            blobs += 1
    return blobs


def _values(image: Image.Image) -> list:
    reader = getattr(image, "get_flattened_data", None)
    if reader is None:
        return list(image.getdata())
    return list(reader())


def _center_square(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))
