"""AniDaily FastAPI 后端。

启动：
    uv run uvicorn src.web.api:app --reload --port 8000
"""

import asyncio
import json
import logging
import logging.handlers
import shutil
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.web.agent import Agent
from src.web.db import ConversationDB
from src.web.serializer import content_to_dict, dict_to_content

# ---- Logging: console + per-session file ----
_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_log_file = _LOG_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

_file_handler = logging.FileHandler(_log_file, encoding="utf-8")
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(_fmt)

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])
logger = logging.getLogger(__name__)
logger.info(f"Log file: {_log_file}")

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

# ---- Database ----
_DB_PATH = PROJECT_ROOT / "anidaily.db"
db = ConversationDB(_DB_PATH)
logger.info(f"Database: {_DB_PATH}")

# 静态文件服务
app.mount("/files", StaticFiles(directory=str(PROJECT_ROOT)), name="files")

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SUPPORTED_VIDEO_EXTS = {".mp4", ".webm", ".mov"}


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
        "clips": output / "videos",
        "final_videos": output / "videos",
        "storyboard_strips": output / "storyboards" / "strips",
        "storyboard_frames": output / "storyboards" / "frames",
        "storyboards": output / "storyboards",
        "clip_scripts": output / "storyboards" / "clip_scripts",
        "scripts": output / "scripts",
    }


SHOWCASE_DIRS = ["stylized", "panels", "storyboards/strips", "storyboards/frames"]
SHOWCASE_LIMIT = 12


@app.get("/api/showcase")
def get_showcase() -> list[dict]:
    """从所有项目收集 showcase 素材（最近修改的图片）。"""
    items: list[dict] = []
    if not PROJECTS_DIR.exists():
        return items
    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        output = proj_dir / "output"
        for sub in SHOWCASE_DIRS:
            d = output / sub
            if not d.exists():
                continue
            for f in d.iterdir():
                if f.is_file() and f.suffix.lower() in SUPPORTED_IMAGE_EXTS:
                    rel = f.relative_to(PROJECT_ROOT)
                    mtime = int(f.stat().st_mtime)
                    items.append({
                        "project": proj_dir.name,
                        "name": f.name,
                        "url": f"/files/{rel}?v={mtime}",
                        "mtime": mtime,
                        "category": sub.split("/")[-1],
                    })
    # Per-project: keep only the latest image
    best: dict[str, dict] = {}
    for item in items:
        proj = item["project"]
        if proj not in best or item["mtime"] > best[proj]["mtime"]:
            best[proj] = item
    result = sorted(best.values(), key=lambda x: x["mtime"], reverse=True)
    return result[:SHOWCASE_LIMIT]


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
    # 创建默认风格设定文件
    style_path = proj_dir / "style.md"
    style_path.write_text(
        "# 漫画风格设定\n\n"
        "## 画风\n- 风格：赛璐璃动画风，干净线条，明亮色彩\n- 色调：明亮活泼\n\n"
        "## 语言\n- 对话：中文\n- 音效：日漫风拟声词\n\n"
        "## 排版\n- 方向：竖向条漫\n- 每条格数：4-6格\n- 气泡：圆形对话框\n\n"
        "## 角色\n- 头身比：正常（5-7头身）\n- 表情：适度夸张\n\n"
        "## 基调\n- 风格：轻松搞笑，校园/职场日常\n- 节奏：中等，对话和动作均衡\n\n"
        "## 场景\n- 背景：简化但有辨识度\n- 时间：现代\n",
        encoding="utf-8",
    )
    return {"name": proj_dir.name, "created": True}


class ProjectRename(BaseModel):
    new_name: str


@app.put("/api/projects/{name}")
def rename_project(name: str, req: ProjectRename) -> dict:
    """重命名项目。"""
    old_dir = _project_path(name)
    if not old_dir.exists():
        return {"renamed": False, "error": "项目不存在"}
    new_dir = _project_path(req.new_name)
    if new_dir.exists():
        return {"renamed": False, "error": "目标名称已存在"}
    old_dir.rename(new_dir)
    return {"renamed": True, "old_name": name, "new_name": new_dir.name}


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
            # 读取 assets.json 元数据
            meta: dict[str, dict] = {}
            meta_path = dir_path / "assets.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            for f in sorted(dir_path.iterdir()):
                if f.name == "assets.json":
                    continue
                if f.is_file():
                    # Split videos dir into clips vs final_videos
                    if category == "clips" and f.name.startswith("final_"):
                        continue
                    if category == "final_videos" and not f.name.startswith("final_"):
                        continue
                    rel = f.relative_to(PROJECT_ROOT)
                    mtime = int(f.stat().st_mtime)
                    item: dict[str, Any] = {
                        "name": f.name,
                        "path": str(f),
                        "url": f"/files/{rel}?v={mtime}",
                    }
                    if f.suffix.lower() in SUPPORTED_IMAGE_EXTS:
                        item["type"] = "image"
                    elif f.suffix.lower() in SUPPORTED_VIDEO_EXTS:
                        item["type"] = "video"
                        # Try to find thumbnail: same dir (for final) or storyboard frames (for clips)
                        thumb_name = f.stem + ".png"
                        thumb_path = f.parent / thumb_name
                        if not thumb_path.exists():
                            thumb_path = _project_path(project) / "output" / "storyboards" / "frames" / thumb_name
                        if thumb_path.exists():
                            thumb_rel = thumb_path.relative_to(PROJECT_ROOT)
                            thumb_mtime = int(thumb_path.stat().st_mtime)
                            item["thumbnail"] = f"/files/{thumb_rel}?v={thumb_mtime}"
                    elif f.suffix.lower() == ".md":
                        item["type"] = "markdown"
                        item["content"] = f.read_text(encoding="utf-8")
                    elif f.suffix.lower() == ".json":
                        item["type"] = "json"
                        item["content"] = f.read_text(encoding="utf-8")
                    # 附加 assets.json 元数据
                    file_meta = meta.get(f.name)
                    if file_meta:
                        if file_meta.get("description"):
                            item["description"] = file_meta["description"]
                        if file_meta.get("source_face"):
                            item["source_face"] = file_meta["source_face"]
                    items.append(item)
        result[category] = items
    # style.md 作为单独分类
    style_path = _project_path(project) / "style.md"
    if style_path.exists():
        rel = style_path.relative_to(PROJECT_ROOT)
        result["style"] = [{
            "name": "style.md",
            "path": str(style_path),
            "url": f"/files/{rel}",
            "type": "markdown",
            "content": style_path.read_text(encoding="utf-8"),
        }]
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


class AssetUpdate(BaseModel):
    path: str
    content: str


@app.put("/api/assets")
def update_asset(req: AssetUpdate) -> dict:
    """更新文本文件内容（md 等）。"""
    p = Path(req.path)
    if not p.exists():
        return {"updated": False, "error": "文件不存在"}
    try:
        p.relative_to(PROJECTS_DIR)
    except ValueError:
        return {"updated": False, "error": "不允许修改此文件"}
    if p.suffix.lower() not in (".md", ".txt"):
        return {"updated": False, "error": "只允许编辑文本文件"}
    p.write_text(req.content, encoding="utf-8")
    return {"updated": True}


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
    message: str = ""
    conversation_id: str | None = None
    image_paths: list[str] | None = None
    project: str | None = None
    lang: str | None = None
    plan_action: str | None = None       # "confirm" | "continue" | "cancel"
    plan_steps: list[dict] | None = None  # steps for "confirm"
    plan_prompt: str | None = None        # extra instruction for "continue"
    plan_auto: bool = True               # auto-execute (only pause at interactive steps)
    mode: str = "comic"                  # "comic" | "storyboard"
    interaction_mode: str = "plan"       # "ask" | "edit" | "plan"


# 对话 agent 实例管理
_agents: dict[str, Agent] = {}


def _get_agent(conversation_id: str | None, project: str | None = None, lang: str = "zh", mode: str = "comic", interaction_mode: str = "plan") -> tuple[str, Agent]:
    """获取或创建对话 agent，优先从内存取，其次从 DB 恢复历史。"""
    # 1. In-memory hit
    if conversation_id and conversation_id in _agents:
        agent = _agents[conversation_id]
        agent.lang = lang
        agent.mode = mode
        agent.interaction_mode = interaction_mode
        return conversation_id, agent

    # 2. DB restore
    if conversation_id:
        history_dicts = db.get_history(conversation_id)
        if history_dicts:
            history = [dict_to_content(d) for d in history_dicts]
            project_dir = _project_path(project) if project else None
            agent = Agent(project_dir=project_dir, lang=lang, history=history, mode=mode, interaction_mode=interaction_mode)
            _agents[conversation_id] = agent
            logger.info(f"Restored agent {conversation_id} with {len(history)} history entries (mode={mode})")
            return conversation_id, agent

    # 3. Brand new conversation
    project_name = project or "default"
    cid = db.create_conversation(project_name, lang)
    project_dir = _project_path(project) if project else None
    agent = Agent(project_dir=project_dir, lang=lang, mode=mode, interaction_mode=interaction_mode)
    _agents[cid] = agent
    return cid, agent


def _sse_line(event: str, data: dict) -> str:
    """格式化一行 SSE。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_chat(agent: Agent, cid: str, message: str, image_paths: list[str] | None) -> AsyncGenerator[str, None]:
    """在线程中运行 agent.chat_stream()，通过 queue 推送 SSE 事件。"""
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    history_len_before = len(agent.history)

    def _run():
        try:
            for event in agent.chat_stream(message, image_paths=image_paths):
                queue.put_nowait(event)
        except Exception as e:
            logger.exception("Agent stream error")
            queue.put_nowait({"event": "error", "message": str(e)})
        finally:
            # Persist new history entries to DB
            for i in range(history_len_before, len(agent.history)):
                try:
                    db.append_history(cid, i, content_to_dict(agent.history[i]))
                except Exception:
                    logger.exception("Failed to persist history entry")
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
    cid, agent = _get_agent(req.conversation_id, req.project, req.lang or "zh", req.mode, req.interaction_mode)

    # Handle plan actions
    if req.plan_action == "confirm" and req.plan_steps:
        agent.plan_confirm(req.plan_steps, auto_execute=req.plan_auto)
        message = req.message or "用户确认了计划，开始执行。"
    elif req.plan_action == "continue":
        agent.plan_continue(req.plan_prompt)
        prompt_part = f"，补充说明：{req.plan_prompt}" if req.plan_prompt else ""
        message = f"用户确认继续{prompt_part}。"
    elif req.plan_action == "cancel":
        agent.plan_cancel()
        return {"status": "cancelled"}
    else:
        message = req.message or "请分析这些图片"

    # Auto-title on first message of a new conversation
    if not req.conversation_id and message:
        title = message[:50].strip()
        db.update_conversation(cid, title=title)

    return StreamingResponse(
        _stream_chat(agent, cid, message, req.image_paths),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ========== 对话历史 ==========

@app.get("/api/conversations")
def list_conversations(project: str) -> list[dict]:
    """列出项目的所有对话。"""
    return db.list_conversations(project)


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict:
    """删除对话及其历史。"""
    _agents.pop(conversation_id, None)
    db.delete_conversation(conversation_id)
    return {"deleted": True}


class SaveMessagesRequest(BaseModel):
    conversation_id: str
    messages: list[dict]


@app.post("/api/conversations/{conversation_id}/messages")
def save_ui_messages(conversation_id: str, req: SaveMessagesRequest) -> dict:
    """替换保存前端 UI 消息（清除旧消息后重新写入）。"""
    db.replace_ui_messages(conversation_id, req.messages)
    return {"saved": len(req.messages)}


@app.get("/api/conversations/{conversation_id}/messages")
def get_ui_messages(conversation_id: str) -> list[dict]:
    """获取对话的 UI 消息。"""
    return db.get_ui_messages(conversation_id)
