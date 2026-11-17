"""用户标识哈希与昵称打码。盐来自 secrets / 环境变量 / 合规配置。"""

from __future__ import annotations

import hashlib


def mask_nickname(nickname: str) -> str:
    """保留第一个字符，其余换成 *。"""

    text = (nickname or "").strip()
    if not text:
        return "*"
    chars = list(text)
    if len(chars) == 1:
        return chars[0]
    return chars[0] + ("*" * (len(chars) - 1))


def hash_user_id(user_id: str, salt: str) -> str:
    material = f"{salt}:{user_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()
