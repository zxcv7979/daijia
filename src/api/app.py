"""FastAPI 应用。页面静态文件缺失时 API 仍然可用。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from src.api.routes import router as api_router
from src.api.ws import router as ws_router
from src.runtime import Context, build_context

logger = logging.getLogger("live_show")

_REPO_ROOT = Path(__file__).resolve().parents[2]


def create_app(root: Path | None = None) -> FastAPI:
    project_root = root or _REPO_ROOT
    ctx = build_context(project_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.ctx.startup()
        try:
            yield
        finally:
            await app.state.ctx.shutdown()

    app = FastAPI(
        title="直播互动演示 P1",
        description="本地模拟的弹幕礼物情绪与虚拟打印。不连接任何直播平台。",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5173",
            "http://localhost:5174",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    app.include_router(ws_router)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _INDEX_HTML

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    _mount_frontend(app, project_root, "admin", "管理控制台")
    _mount_frontend(app, project_root, "overlay", "特效预览")
    return app


def _mount_frontend(app: FastAPI, root: Path, name: str, title: str) -> None:
    dist = root / "apps" / name / "dist"
    if not (dist / "index.html").is_file():
        logger.info("%s 页面尚未构建：%s", title, dist)
        return

    app.add_api_route(
        f"/{name}",
        _redirect_to(name),
        methods=["GET"],
        include_in_schema=False,
        name=f"redirect_{name}",
    )
    app.mount(f"/{name}", StaticFiles(directory=dist, html=True), name=name)


def _redirect_to(name: str):
    async def _redirect() -> RedirectResponse:
        return RedirectResponse(url=f"/{name}/")

    return _redirect


_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>直播互动演示</title>
  <style>
    body { font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background:#12141a; color:#e8e6e3; margin:0; }
    main { max-width: 720px; margin: 8vh auto; padding: 24px; }
    a { color: #ffb020; }
    code { background:#1c2030; padding: 2px 6px; }
  </style>
</head>
<body>
  <main>
    <h1>直播互动演示 P1</h1>
    <p>这是本地模拟。真实采集默认关闭，没有连接任何直播平台，打印也是虚拟进度。</p>
    <ul>
      <li><a href="/admin/">管理控制台</a></li>
      <li><a href="/overlay/">特效预览</a></li>
      <li><a href="/docs">API 文档</a></li>
    </ul>
    <p>如果页面打不开，先在仓库根目录执行 <code>npm run build</code>，或分别运行 Vite 开发服务。</p>
  </main>
</body>
</html>
"""
