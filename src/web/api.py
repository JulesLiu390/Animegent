"""AniDaily FastAPI 后端。

启动：
    uv run uvicorn src.web.api:app --reload --port 8000
"""

import asyncio
import json
import logging
import shutil
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.web.agent import Agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="AniDaily API")

# CORS for React dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
PROJECTS_DIR = PROJECT_ROOT / "projects"
PROJECTS_DIR.mkdir(exist_ok=True)

# 静态文件服务
app.mount("/files", StaticFiles(directory=str(PROJECT_ROOT)), name="files")

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


# ========== 项目管理 ==========

def _project_path(name: str) -> Path:
    """返回项目根目录，校验名称安全性。"""
    safe = Path(name).name  # 防止路径遍历
    return PROJECTS_DIR / safe


def _asset_dirs(project: str) -> dict[str, Path]:
    """返回项目的素材目录映射。"""
    proj = _project_path(project)
    output = proj / "output"
    return {
        "originals": proj / "input",
        "characters": output / "stylized",
        "faces": output / "faces",
        "scenes": output / "scenes" / "stylized",
        "scenes_raw": output / "scenes" / "no_people",
        "panels": output / "panels",
        "scripts": output / "scripts",
    }


class ProjectCreate(BaseModel):
    name: str


@app.get("/api/projects")
def list_projects() -> list[dict]:
    """列出所有项目。"""
    projects = []
    if PROJECTS_DIR.exists():
        for d in sorted(PROJECTS_DIR.iterdir()):
            if d.is_dir():
                projects.append({"name": d.name})
    return projects


@app.post("/api/projects")
def create_project(req: ProjectCreate) -> dict:
    """创建新项目。"""
    proj_dir = _project_path(req.name)
    if proj_dir.exists():
        return {"name": proj_dir.name, "created": False}
    proj_dir.mkdir(parents=True)
    for d in _asset_dirs(req.name).values():
        d.mkdir(parents=True, exist_ok=True)
    return {"name": proj_dir.name, "created": True}


@app.delete("/api/projects/{name}")
def delete_project(name: str) -> dict:
    """删除项目。"""
    proj_dir = _project_path(name)
    if not proj_dir.exists():
        return {"deleted": False, "error": "项目不存在"}
    shutil.rmtree(proj_dir)
    return {"deleted": True}


# ========== 素材管理 ==========

@app.get("/api/assets")
def list_assets(project: str) -> dict[str, list[dict]]:
    """列出项目的所有分类素材。"""
    result: dict[str, list[dict]] = {}
    for category, dir_path in _asset_dirs(project).items():
        items = []
        if dir_path.exists():
            for f in sorted(dir_path.iterdir()):
                if f.name == "assets.json":
                    continue
                if f.is_file():
                    rel = f.relative_to(PROJECT_ROOT)
                    item: dict[str, Any] = {
                        "name": f.name,
                        "path": str(f),
                        "url": f"/files/{rel}",
                    }
                    if f.suffix.lower() in SUPPORTED_IMAGE_EXTS:
                        item["type"] = "image"
                    elif f.suffix.lower() == ".md":
                        item["type"] = "markdown"
                        item["content"] = f.read_text(encoding="utf-8")
                    elif f.suffix.lower() == ".json":
                        item["type"] = "json"
                    items.append(item)
        result[category] = items
    return result


class AssetDelete(BaseModel):
    path: str


@app.delete("/api/assets")
def delete_asset(req: AssetDelete) -> dict:
    """删除单个素材文件。"""
    p = Path(req.path)
    # 安全检查：只允许删除 projects/ 下的文件
    if not p.exists():
        return {"deleted": False, "error": "文件不存在"}
    try:
        p.relative_to(PROJECTS_DIR)
    except ValueError:
        return {"deleted": False, "error": "不允许删除此文件"}
    p.unlink()
    return {"deleted": True}


@app.post("/api/upload")
async def upload_image(file: UploadFile, project: str) -> dict:
    """上传图片到项目目录。"""
    upload_dir = _project_path(project) / "input"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # UUID 文件名，保留原始扩展名，避免同名覆盖
    ext = Path(file.filename).suffix or ".png"
    unique_name = f"{uuid.uuid4().hex[:8]}{ext}"
    file_path = upload_dir / unique_name
    content = await file.read()
    file_path.write_bytes(content)

    rel = file_path.relative_to(PROJECT_ROOT)
    return {
        "path": str(file_path),
        "url": f"/files/{rel}",
        "name": unique_name,
    }


# ========== 对话 (SSE 流式) ==========

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    image_paths: list[str] | None = None
    project: str | None = None


# 对话 agent 实例管理
_agents: dict[str, Agent] = {}


def _get_agent(conversation_id: str | None, project: str | None = None) -> tuple[str, Agent]:
    """获取或创建对话 agent。"""
    if conversation_id and conversation_id in _agents:
        return conversation_id, _agents[conversation_id]
    cid = conversation_id or str(uuid.uuid4())
    project_dir = _project_path(project) if project else None
    agent = Agent(project_dir=project_dir)
    _agents[cid] = agent
    return cid, agent


def _sse_line(event: str, data: dict) -> str:
    """格式化一行 SSE。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_chat(agent: Agent, cid: str, message: str, image_paths: list[str] | None) -> AsyncGenerator[str, None]:
    """在线程中运行 agent.chat_stream()，通过 queue 推送 SSE 事件。"""
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    def _run():
        try:
            for event in agent.chat_stream(message, image_paths=image_paths):
                queue.put_nowait(event)
        except Exception as e:
            logger.exception("Agent stream error")
            queue.put_nowait({"event": "error", "message": str(e)})
        finally:
            queue.put_nowait(None)  # sentinel

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run)

    # 先发送 conversation_id
    yield _sse_line("conversation_id", {"conversation_id": cid})

    while True:
        event = await queue.get()
        if event is None:
            break
        event_type = event.get("event", "unknown")
        yield _sse_line(event_type, event)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """SSE 流式对话接口。"""
    cid, agent = _get_agent(req.conversation_id, req.project)

    return StreamingResponse(
        _stream_chat(agent, cid, req.message, req.image_paths),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
