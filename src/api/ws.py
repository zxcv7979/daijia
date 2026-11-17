"""本地 WebSocket。重连时用 since_seq 补发 30 秒缓冲。"""

from __future__ import annotations

import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.runtime import Context

router = APIRouter()


def _ctx(websocket: WebSocket) -> Context:
    return websocket.app.state.ctx


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    ctx = _ctx(websocket)
    queue = ctx.bus.subscribe()
    try:
        since = _parse_since(websocket.query_params.get("since_seq"))
        await websocket.send_json(
            {
                "v": 1,
                "kind": "hello",
                "ts": time.time(),
                "data": {"buffer_sec": ctx.bus.buffer_sec, "latest_seq": ctx.bus.seq},
            }
        )
        sent: set[int] = set()
        if since is not None:
            replay, gap = ctx.bus.replay_since(since)
            if gap:
                buffered = ctx.bus.buffered_messages()
                oldest = buffered[0]["seq"] if buffered else None
                await websocket.send_json(
                    {
                        "v": 1,
                        "kind": "buffer_gap",
                        "ts": time.time(),
                        "data": {"requested": since, "oldest_seq": oldest},
                    }
                )
            for message in replay:
                sent.add(message["seq"])
                await websocket.send_json(message)
            # 控制消息，不进 30 秒缓冲。客户端可据此知道补发结束。
            await websocket.send_json(
                {
                    "v": 1,
                    "kind": "replay_done",
                    "ts": time.time(),
                    "data": {"count": len(replay)},
                }
            )
        while True:
            message = await queue.get()
            seq = int(message["seq"])
            if seq in sent:
                continue
            sent.add(seq)
            if len(sent) > 4000:
                sent = set(sorted(sent)[-1000:])
            await websocket.send_json(message)
    except WebSocketDisconnect:
        return
    finally:
        ctx.bus.unsubscribe(queue)


def _parse_since(raw: str | None) -> int | None:
    """负数或省略表示只听新消息。0 表示把缓冲里还在的消息都补上。"""

    if raw is None or raw == "":
        return None
    value = int(raw)
    if value < 0:
        return None
    return value
