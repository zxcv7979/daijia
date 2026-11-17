"""进程内总线 + 30 秒环形缓冲。

WebSocket 重连时按 seq 把缓冲里错过的消息补发给客户端。
缓冲只保存已经脱敏的信封，不保存 raw_ref。
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from src.clock import SystemClock

BUFFERED_KINDS = frozenset({"event", "emotion", "fx_cue", "print_job", "print_progress"})


class EventBus:
    def __init__(self, buffer_sec: float = 30, clock: SystemClock | None = None) -> None:
        if buffer_sec != 30:
            raise ValueError("重连缓冲固定为 30 秒")
        self.buffer_sec = buffer_sec
        self.clock = clock or SystemClock()
        self.seq = 0
        self._buffer: deque[tuple[float, int, dict[str, Any]]] = deque()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        if kind not in BUFFERED_KINDS:
            raise ValueError(f"不支持的消息类型 {kind}")
        self._evict()
        self.seq += 1
        message = {
            "v": 1,
            "kind": kind,
            "seq": self.seq,
            "ts": self.clock.time(),
            "data": data,
        }
        self._buffer.append((message["ts"], message["seq"], message))
        for queue in list(self._subscribers):
            queue.put_nowait(message)
        return message

    def replay_since(self, since_seq: int) -> tuple[list[dict[str, Any]], bool]:
        """返回 seq 大于 since_seq 的消息，以及请求是否已经早于缓冲区。"""

        self._evict()
        if since_seq <= 0:
            # 0 表示新客户端，把窗口里还在的消息送出去，不把它当成断线空洞。
            return [item[2] for item in self._buffer], False
        if not self._buffer:
            # 缓冲是空的，但序号已经往前走，说明错过的消息都过期了。
            return [], self.seq > since_seq
        oldest = self._buffer[0][1]
        # oldest 比游标的下一条还大，中间有消息已经被挤出 30 秒窗口。
        gap = oldest > since_seq + 1
        messages = [item[2] for item in self._buffer if item[1] > since_seq]
        return messages, gap

    def buffered_messages(self) -> list[dict[str, Any]]:
        self._evict()
        return [item[2] for item in self._buffer]

    def _evict(self) -> None:
        now = self.clock.time()
        while self._buffer and (now - self._buffer[0][0]) > self.buffer_sec:
            self._buffer.popleft()
