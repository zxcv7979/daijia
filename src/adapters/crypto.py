"""原文落盘加密。只用标准库：HMAC-SHA256 计数器流 + HMAC 校验。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os


def derive_key(salt: str) -> bytes:
    return hashlib.sha256(f"{salt}:raw-at-rest".encode("utf-8")).digest()


def _keystream(key: bytes, nonce: bytes, size: int) -> bytes:
    chunks = bytearray()
    counter = 0
    while len(chunks) < size:
        block = hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        chunks.extend(block)
        counter += 1
    return bytes(chunks[:size])


def encrypt(key: bytes, plaintext: bytes) -> str:
    nonce = os.urandom(16)
    stream = _keystream(key, nonce, len(plaintext))
    ciphertext = bytes(left ^ right for left, right in zip(plaintext, stream, strict=True))
    tag = hmac.new(key, b"enc1" + nonce + ciphertext, hashlib.sha256).digest()
    return base64.b64encode(nonce + tag + ciphertext).decode("ascii")


def decrypt(key: bytes, token: str) -> bytes:
    raw = base64.b64decode(token.encode("ascii"))
    if len(raw) < 48:
        raise ValueError("密文太短")
    nonce, tag, ciphertext = raw[:16], raw[16:48], raw[48:]
    expected = hmac.new(key, b"enc1" + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("密文校验失败")
    stream = _keystream(key, nonce, len(ciphertext))
    return bytes(left ^ right for left, right in zip(ciphertext, stream, strict=True))
