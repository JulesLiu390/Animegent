"""AniDaily FastAPI 后端。

启动：
    uv run uvicorn src.web.api:app --reload --port 8000
"""

import asyncio
import json
import logging
import logging.handlers
import re
import shutil
import threading
import uuid
from collections.abc import AsyncGenerator, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.providers import llm
from src.providers import settings as provider_settings
from src.web import features
from src.web.agent import JobManager, Session, Sessions
from src.web.agent import skills as agent_skills
from src.web.db import ConversationDB, conversation_turns, job_view, new_id, step_view

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


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 上次退出时还在执行的 turn / 后台任务都已中断。只在服务启动时做：测试或别的进程导入这个模块时不能动正在运行的实例
    db.interrupt_running_turns("服务重启，任务中断")
    jobs.recover()
    yield


app = FastAPI(title="AniDaily API", lifespan=lifespan)

# CORS for React dev server：只允许本机 / 局域网页面调用（接口能读写 API Key 配置，不能对任意网站开放）
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"https?://(localhost|127\.0\.0\.1|\[::1\]|10(\.\d{1,3}){3}|192\.168(\.\d{1,3}){2}"
        r"|172\.(1[6-9]|2\d|3[01])(\.\d{1,3}){2})(:\d+)?"
    ),
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
jobs = JobManager(db)
sessions = Sessions(db, jobs, PROJECTS_DIR)

# 静态文件服务：只暴露 projects/ 下的素材（项目根目录里还有 settings.json、.env 等含 API Key 的文件）
app.mount("/files/projects", StaticFiles(directory=str(PROJECTS_DIR)), name="files")

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SUPPORTED_VIDEO_EXTS = {".mp4", ".webm", ".mov"}


# ========== 项目管理 ==========

_INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _project_path(name: str) -> Path:
    """返回项目根目录；名称不合法（空、. / ..、含路径分隔符等）时返回 400。"""
    safe = (name or "").strip()
    if not safe or safe.startswith(".") or _INVALID_NAME_CHARS.search(safe) or len(safe) > 80:
        raise HTTPException(status_code=400, detail="项目名称不合法：不能为空、不能以 . 开头，也不能包含 / \\ : * ? \" < > |")
    return PROJECTS_DIR / safe


def _project_file(path: str) -> Path:
    """解析素材路径，只允许 projects/ 下的文件（防止 ../ 跳出目录）。"""
    p = Path(path).resolve()
    if not p.is_relative_to(PROJECTS_DIR.resolve()):
        raise HTTPException(status_code=403, detail="只能操作项目目录下的文件")
    return p


def _file_url(p: Path) -> str:
    rel = p.resolve().relative_to(PROJECT_ROOT.resolve())
    return f"/files/{rel.as_posix()}?v={int(p.stat().st_mtime)}"


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
        "drafts": output / "scripts" / "strips",  # 分镜草稿（draft_strip 写的）
        "layouts": output / "layouts",  # 版式草图；同名的 .py 画图代码不列出来
    }


# 分镜模式的素材分类：分镜休眠时新项目不建这些目录（已有的文件照常列出）
_STORYBOARD_CATEGORIES = {"clips", "final_videos", "storyboard_strips", "storyboard_frames", "storyboards", "clip_scripts"}


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


def _project_info(d: Path) -> dict:
    """项目卡片信息：封面（最近生成的图片）、素材数量、最后修改时间。"""
    cover: tuple[float, Path] | None = None
    count = 0
    latest = d.stat().st_mtime
    output = d / "output"
    for sub in ["stylized", "panels", "storyboards/strips", "storyboards/frames", "scenes/stylized", "faces"]:
        folder = output / sub
        if not folder.is_dir():
            continue
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in SUPPORTED_IMAGE_EXTS:
                count += 1
                mtime = f.stat().st_mtime
                latest = max(latest, mtime)
                if sub != "faces" and (cover is None or mtime > cover[0]):
                    cover = (mtime, f)
    return {
        "name": d.name,
        "cover": _file_url(cover[1]) if cover else None,
        "image_count": count,
        "updated_at": datetime.fromtimestamp(latest).isoformat(),
    }


@app.get("/api/projects")
def list_projects() -> list[dict]:
    """列出所有项目（含封面和素材数量）。"""
    projects = []
    if PROJECTS_DIR.exists():
        for d in sorted(PROJECTS_DIR.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                projects.append(_project_info(d))
    return projects


@app.post("/api/projects")
def create_project(req: ProjectCreate) -> dict:
    """创建新项目。"""
    proj_dir = _project_path(req.name)
    if proj_dir.exists():
        return {"name": proj_dir.name, "created": False}
    proj_dir.mkdir(parents=True)
    for category, d in _asset_dirs(proj_dir.name).items():
        if category in _STORYBOARD_CATEGORIES and not features.STORYBOARD:
            continue
        d.mkdir(parents=True, exist_ok=True)
    # 创建默认风格设定文件（中文 + 英文）
    (proj_dir / "style.md").write_text(
        "# 漫画风格设定\n\n"
        "## 画风\n- 风格：赛璐璃动画风，干净线条，明亮色彩\n- 色调：明亮活泼\n\n"
        "## 语言\n- 对话：中文\n- 音效：日漫风拟声词\n\n"
        "## 排版\n- 方向：竖向条漫\n- 每条格数：4-6格\n- 气泡：圆形对话框\n\n"
        "## 角色\n- 头身比：正常（5-7头身）\n- 表情：适度夸张\n\n"
        "## 基调\n- 风格：轻松搞笑，校园/职场日常\n- 节奏：中等，对话和动作均衡\n\n"
        "## 场景\n- 背景：简化但有辨识度\n- 时间：现代\n",
        encoding="utf-8",
    )
    (proj_dir / "style_en.md").write_text(
        "# Comic Style Guide\n\n"
        "## Art Style\n- Style: Cel-shaded anime, clean lines, bright colors\n- Tone: Bright and lively\n\n"
        "## Language\n- Dialogue: English\n- Sound effects: Japanese manga-style onomatopoeia\n\n"
        "## Layout\n- Direction: Vertical comic strip\n- Panels per strip: 4-6\n- Bubbles: Round speech bubbles\n\n"
        "## Characters\n- Proportions: Normal (5-7 heads tall)\n- Expressions: Moderately exaggerated\n\n"
        "## Tone\n- Style: Light-hearted and comedic, slice-of-life\n- Pacing: Medium, balanced dialogue and action\n\n"
        "## Scenes\n- Backgrounds: Simplified but recognizable\n- Setting: Modern day\n",
        encoding="utf-8",
    )
    return {"name": proj_dir.name, "created": True}


class ProjectRename(BaseModel):
    new_name: str


@app.put("/api/projects/{name}")
def rename_project(name: str, req: ProjectRename) -> dict:
    """重命名项目：目录改名，对话记录里的路径一起更新。"""
    old_dir = _project_path(name)
    if not old_dir.exists():
        return {"renamed": False, "error": "项目不存在"}
    new_dir = _project_path(req.new_name)
    if new_dir.exists():
        return {"renamed": False, "error": "目标名称已存在"}
    conversation_ids = db.conversation_ids(old_dir.name)
    if sessions.busy(conversation_ids) or any(j["status"] == "running" for cid in conversation_ids for j in db.list_jobs(cid, unfinished=True)):
        return {"renamed": False, "error": "这个项目还有任务在执行，请等它结束后再改名"}
    old_dir.rename(new_dir)
    db.rename_project(old_dir.name, new_dir.name, [
        (f"{old_dir}/", f"{new_dir}/"),
        (f"/files/projects/{old_dir.name}/", f"/files/projects/{new_dir.name}/"),
    ])
    # 内存里的运行时还拿着旧路径：丢掉，下次按新路径重建
    for cid in conversation_ids:
        sessions.drop(cid)
    return {"renamed": True, "old_name": old_dir.name, "new_name": new_dir.name}


@app.delete("/api/projects/{name}")
def delete_project(name: str) -> dict:
    """删除项目（含素材和对话记录）。"""
    proj_dir = _project_path(name)
    if not proj_dir.exists():
        return {"deleted": False, "error": "项目不存在"}
    for cid in db.conversation_ids(proj_dir.name):
        sessions.drop(cid)
        jobs.cancel_queued(cid)
    shutil.rmtree(proj_dir)
    db.delete_project(proj_dir.name)
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
                    if category == "layouts" and f.suffix.lower() not in SUPPORTED_IMAGE_EXTS:
                        continue
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
                        if file_meta.get("name"):
                            item["title"] = file_meta["name"]
                        if file_meta.get("description"):
                            item["description"] = file_meta["description"]
                        if file_meta.get("source_face"):
                            item["source_face"] = file_meta["source_face"]
                    items.append(item)
        result[category] = items
    # style.md / style_en.md 作为单独分类
    style_items = []
    for style_name in ("style.md", "style_en.md"):
        sp = _project_path(project) / style_name
        if sp.exists():
            rel = sp.relative_to(PROJECT_ROOT)
            style_items.append({
                "name": style_name,
                "path": str(sp),
                "url": f"/files/{rel}",
                "type": "markdown",
                "content": sp.read_text(encoding="utf-8"),
            })
    if style_items:
        result["style"] = style_items
    skill_items = _skill_assets(_project_path(project))
    if skill_items:
        result["skills"] = skill_items
    return result


def _skill_assets(proj_dir: Path) -> list[dict]:
    """技能（SKILL.md）：内置的只读；项目自己的（projects/<项目>/skills/）可以在界面里改。分镜模式休眠时不列分镜的技能。"""
    items = []
    for skill in agent_skills.discover(proj_dir).values():
        if not features.STORYBOARD and skill.scopes and "comic" not in skill.scopes:
            continue
        try:
            content = skill.text()
        except (agent_skills.SkillError, OSError):
            continue
        item: dict[str, Any] = {
            "name": skill.id, "path": str(skill.file), "url": "", "type": "markdown", "content": content,
            "title": skill.name, "description": skill.description, "source": skill.source,
        }
        if skill.source == "project":
            item["url"] = f"/files/{skill.file.relative_to(PROJECT_ROOT)}?v={int(skill.file.stat().st_mtime)}"
        else:
            item["readonly"] = True
        items.append(item)
    return items


class AssetDelete(BaseModel):
    path: str


@app.delete("/api/assets")
def delete_asset(req: AssetDelete) -> dict:
    """删除单个素材文件（同时去掉 assets.json 里的记录）。"""
    p = _project_file(req.path)
    if not p.is_file():
        return {"deleted": False, "error": "文件不存在"}
    p.unlink()
    meta_path = p.parent / "assets.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.pop(p.name, None) is not None:
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.warning(f"更新 {meta_path} 失败", exc_info=True)
    return {"deleted": True}


class AssetUpdate(BaseModel):
    path: str
    content: str


@app.put("/api/assets")
def update_asset(req: AssetUpdate) -> dict:
    """更新文本文件内容（md 等）。"""
    p = _project_file(req.path)
    if not p.is_file():
        return {"updated": False, "error": "文件不存在"}
    if p.suffix.lower() not in (".md", ".txt"):
        return {"updated": False, "error": "只允许编辑文本文件"}
    p.write_text(req.content, encoding="utf-8")
    return {"updated": True}


@app.post("/api/upload")
async def upload_image(file: UploadFile, project: str) -> dict:
    """上传图片到项目目录。"""
    upload_dir = _project_path(project) / "input"
    ext = Path(file.filename or "").suffix.lower() or ".png"
    if ext not in SUPPORTED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail=f"只支持上传图片（{', '.join(sorted(SUPPORTED_IMAGE_EXTS))}）")
    upload_dir.mkdir(parents=True, exist_ok=True)

    # UUID 文件名，保留原始扩展名，避免同名覆盖
    unique_name = f"{uuid.uuid4().hex[:8]}{ext}"
    file_path = upload_dir / unique_name
    file_path.write_bytes(await file.read())
    return {
        "path": str(file_path),
        "url": _file_url(file_path),
        "name": unique_name,
    }


# ========== API 设置（服务商与模型） ==========

class ProviderIn(BaseModel):
    name: str
    api_format: str = "openai_compatible"
    base_url: str = ""
    api_keys: list[str] | None = None  # None：保留已保存的 Key
    models: list[str] = []


class ModelAssignmentIn(BaseModel):
    provider_id: str = ""
    model: str = ""
    format: str = ""
    size: str = ""


class ModelsIn(BaseModel):
    chat: ModelAssignmentIn | None = None
    vision: ModelAssignmentIn | None = None
    image: ModelAssignmentIn | None = None
    video: ModelAssignmentIn | None = None


class ProbeIn(BaseModel):
    """获取模型列表 / 测试连接：可以用表单里新填的 Key，也可以用已保存服务商的 Key。"""
    provider_id: str | None = None
    api_format: str = "openai_compatible"
    base_url: str = ""
    api_keys: list[str] | None = None
    model: str = ""


def _settings_payload() -> dict:
    """服务商列表（API Key 已脱敏）、各用途的模型分配，以及功能开关（前端据此隐藏休眠的功能）。"""
    return {**provider_settings.public_dict(), "features": features.public()}


@app.get("/api/settings")
def get_api_settings() -> dict:
    """服务商列表（API Key 已脱敏）和各用途的模型分配。"""
    return _settings_payload()


@app.post("/api/settings/providers")
def create_api_provider(req: ProviderIn) -> dict:
    try:
        provider_settings.create_provider(req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _settings_payload()


@app.put("/api/settings/providers/{provider_id}")
def update_api_provider(provider_id: str, req: ProviderIn) -> dict:
    try:
        provider_settings.update_provider(provider_id, req.model_dump())
    except KeyError:
        raise HTTPException(status_code=404, detail="服务商不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _settings_payload()


@app.delete("/api/settings/providers/{provider_id}")
def delete_api_provider(provider_id: str) -> dict:
    if not provider_settings.delete_provider(provider_id):
        raise HTTPException(status_code=404, detail="服务商不存在")
    return _settings_payload()


@app.put("/api/settings/models")
def update_model_settings(req: ModelsIn) -> dict:
    try:
        provider_settings.update_models(req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _settings_payload()


def _probe_keys(req: ProbeIn) -> list[str]:
    """表单里填了 Key 就用新填的，否则用已保存服务商的 Key；本地服务可以没有 Key。"""
    keys = [k.strip() for k in req.api_keys or [] if k.strip()]
    if not keys and req.provider_id:
        provider = provider_settings.load().provider(req.provider_id)
        if provider:
            keys = provider.api_keys
    return keys or [""]


@app.post("/api/settings/models/fetch")
def fetch_provider_models(req: ProbeIn) -> dict:
    try:
        return {"models": llm.fetch_models(req.api_format, req.base_url, _probe_keys(req)[0])}
    except Exception as e:
        return {"models": [], "error": str(e)}


@app.post("/api/settings/test")
def test_api_provider(req: ProbeIn) -> dict:
    """逐个测试 Key：填了模型名就用它发一句 hi，否则测试能否获取模型列表。"""
    results = []
    for key in _probe_keys(req):
        label = provider_settings.mask_key(key) if key else "（无 Key）"
        try:
            if req.model:
                reply = llm.ping(req.api_format, req.base_url, key, req.model)
                message = f"{req.model} 回复：{reply or '（空）'}"
            else:
                models = llm.fetch_models(req.api_format, req.base_url, key)
                message = f"连接成功，获取到 {len(models)} 个模型"
            results.append({"key": label, "ok": True, "message": message})
        except Exception as e:
            results.append({"key": label, "ok": False, "message": str(e)[:300]})
    return {"ok": any(r["ok"] for r in results), "results": results}


# ========== 对话：Session → Turn → Step（SSE 流式） ==========

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class Attachment(BaseModel):
    path: str
    url: str = ""
    name: str = ""
    fileType: str | None = None  # noqa: N815  与前端字段一致
    content: str | None = None
    description: str | None = None


class RunOptions(BaseModel):
    lang: str | None = None
    mode: str = "comic"                  # "comic" | "storyboard"（分镜模式休眠时按 comic 处理，见 features.py）
    interaction_mode: str = "confirm"    # "ask" 讨论 | "confirm" 生成前确认 | "auto" 自动执行


class ChatRequest(RunOptions):
    conversation_id: str | None = None   # 不传则新建对话
    project: str | None = None
    turn_id: str | None = None           # 前端生成的 turn id（可选），这样界面上可以先显示用户消息
    text: str = ""                       # 发给模型的文字
    display: str | None = None           # 界面上显示的文字（和 text 不同时才传）
    attachments: list[Attachment] = []
    title: str | None = None             # 对话标题（新对话的第一条消息）


class ResumeRequest(RunOptions):
    # step_id → {"approve": bool, "note"?: str}（批准 / 拒绝生成）或 {"value": ...}（卡片里的选择）
    responses: dict[str, dict]


class RetryRequest(RunOptions):
    turn_id: str | None = None           # 重新生成的这一轮用的新 id（可选）
    text: str | None = None              # 编辑后的文字；不传则原样重试


def _new_turn_id(requested: str | None) -> str:
    if requested and _ID_RE.match(requested) and not db.get_turn(requested):
        return requested
    return new_id()


def _sse_line(event: dict) -> str:
    return f"event: {event.get('event', 'message')}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def _stream(session: Session, work: Callable[[], Iterator[dict]], first: list[dict] | None = None) -> StreamingResponse:
    """在线程里执行 work（持有这个对话的锁），把事件和后台任务的进度一起通过 SSE 推送；客户端断开时停止任务。"""

    async def events() -> AsyncGenerator[str, None]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        finished = threading.Event()
        disconnected = threading.Event()

        def emit(event: dict | None) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def run() -> None:
            try:
                # 同一对话同时只跑一个任务：上一个任务刚被停止时等它收尾
                if not session.run_lock.acquire(timeout=20):
                    emit({"event": "error", "message": "这个对话还有任务在执行，请稍后再试"})
                    return
                try:
                    session.cancel_event.clear()
                    if disconnected.is_set():
                        return  # 排队等锁的时候客户端已经断开（例如点了停止），不再执行
                    jobs.subscribe(session.id, emit)
                    try:
                        for event in work():
                            emit(event)
                    finally:
                        jobs.unsubscribe(session.id, emit)
                    emit({"event": "done"})
                finally:
                    session.run_lock.release()
            except Exception as e:
                logger.exception("对话执行出错")
                emit({"event": "error", "message": str(e) or type(e).__name__})
            finally:
                finished.set()
                emit(None)

        loop.run_in_executor(None, run)
        try:
            for event in first or []:
                yield _sse_line(event)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # 心跳：长时间生成图片时保持连接，也能及时发现客户端已断开
                    continue
                if event is None:
                    break
                yield _sse_line(event)
        finally:
            disconnected.set()
            if not finished.is_set():
                session.stop()  # 客户端断开（关闭页面、点了停止）：停止任务

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _turn_session(turn_id: str) -> tuple[dict, Session]:
    turn = db.get_turn(turn_id)
    session = sessions.get(turn["conversation_id"]) if turn else None
    if not turn or not session:
        raise HTTPException(status_code=404, detail="这条消息不存在")
    return turn, session


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """发送一条消息，开始新的一轮（SSE）。没有 conversation_id 时新建对话。"""
    session = sessions.get(req.conversation_id)
    if req.conversation_id and session is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    if session is None:
        session = sessions.create(_project_path(req.project) if req.project else None, req.lang or "zh")
    turn_id = _new_turn_id(req.turn_id)
    input_data: dict = {"text": req.text.strip(), "attachments": [a.model_dump(exclude_none=True) for a in req.attachments]}
    if req.display and req.display.strip() != input_data["text"]:
        input_data["display"] = req.display.strip()
    title = " ".join((req.title or req.display or req.text).split())[:60]

    def work() -> Iterator[dict]:
        conv = db.get_conversation(session.id)
        if title and conv and not conv["title"]:
            db.update_conversation(session.id, title=title)
        yield from session.send(turn_id, input_data, lang=req.lang or "zh", mode=req.mode, interaction=req.interaction_mode)

    return _stream(session, work, first=[{"event": "conversation", "conversation_id": session.id}])


@app.post("/api/turns/{turn_id}/resume")
async def resume_turn(turn_id: str, req: ResumeRequest):
    """批准 / 拒绝生成，或者提交卡片里的选择：这一轮接着执行（SSE）。"""
    _, session = _turn_session(turn_id)

    def work() -> Iterator[dict]:
        turn = db.get_turn(turn_id)
        if not turn or turn["status"] not in ("awaiting_approval", "awaiting_input"):
            yield {"event": "error", "message": "这一轮已经不在等待操作了"}
            return
        yield from session.resume(turn, req.responses, lang=req.lang or "zh", mode=req.mode, interaction=req.interaction_mode)

    return _stream(session, work)


@app.post("/api/turns/{turn_id}/retry")
async def retry_turn(turn_id: str, req: RetryRequest):
    """从这一轮重新开始（重试 / 编辑后重新发送）：这一轮及之后的内容删掉，用同样（或编辑后）的输入重新执行（SSE）。"""
    turn, session = _turn_session(turn_id)
    if turn["legacy"]:
        raise HTTPException(status_code=400, detail="旧版对话的消息不能重试")
    new_turn_id = _new_turn_id(req.turn_id)

    def work() -> Iterator[dict]:
        current = db.get_turn(turn_id)
        if not current:
            yield {"event": "error", "message": "这条消息不存在"}
            return
        input_data = dict(current["input"] or {})
        if req.text is not None:
            input_data["text"] = req.text.strip()
            input_data.pop("display", None)
        session.rewind(current)
        yield from session.send(new_turn_id, input_data, lang=req.lang or "zh", mode=req.mode, interaction=req.interaction_mode)

    return _stream(session, work)


@app.delete("/api/turns/{turn_id}")
def delete_turn(turn_id: str) -> dict:
    """删除这一轮及之后的内容，模型也会忘掉这些内容。"""
    turn, session = _turn_session(turn_id)
    if turn["legacy"]:
        raise HTTPException(status_code=400, detail="旧版对话的消息不能删除")
    if not session.run_lock.acquire(timeout=20):
        raise HTTPException(status_code=409, detail="这个对话还有任务在执行，请先停止")
    try:
        deleted = session.rewind(turn)
    finally:
        session.run_lock.release()
    return {"deleted": deleted}


class StopRequest(BaseModel):
    conversation_id: str


@app.post("/api/chat/stop")
def stop_chat(req: StopRequest) -> dict:
    """停止对话里正在执行的任务；没有任务在跑时，最后一轮如果在等批准 / 选择，按停止处理，排队的后台任务取消。"""
    session = sessions.get(req.conversation_id)
    if not session:
        return {"stopping": False}
    running = session.run_lock.locked()
    session.stop()
    if not running and session.run_lock.acquire(timeout=5):
        try:
            for _ in session.settle("用户已停止"):
                pass
            jobs.cancel_queued(session.id)
        finally:
            session.run_lock.release()
    return {"stopping": running}


class StepUpdate(BaseModel):
    verdict: str | None = None


@app.patch("/api/steps/{step_id}")
def update_step(step_id: str, req: StepUpdate) -> dict:
    """记录用户对生成结果的处理：accepted 满意 / rejected 删除 / revised 要求修改。"""
    step = db.get_step(step_id)
    if not step:
        raise HTTPException(status_code=404, detail="不存在")
    if req.verdict not in (None, "accepted", "rejected", "revised"):
        raise HTTPException(status_code=400, detail="verdict 不合法")
    step = db.update_step(step_id, verdict=req.verdict)
    return step_view(step, db.get_job(step["job_id"]) if step["job_id"] else None)


@app.get("/api/conversations/{conversation_id}/jobs")
def list_jobs(conversation_id: str, ids: str = "", active: bool = False) -> list[dict]:
    """后台生成任务的状态（前端在对话流结束后轮询）。ids：逗号分隔；active：只要还没结束的。"""
    id_list = [i for i in ids.split(",") if i]
    rows = db.list_jobs(conversation_id, ids=id_list) if id_list else db.list_jobs(conversation_id, unfinished=active) if active else db.list_jobs(conversation_id)
    return [job_view(j) for j in rows]


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    """取消还在排队的生成任务（已经开始生成的会照常完成）。"""
    job = jobs.cancel(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job_view(job)


# ========== 对话历史 ==========

@app.get("/api/conversations")
def list_conversations(project: str) -> list[dict]:
    """列出项目的所有对话。"""
    return db.list_conversations(project)


class ConversationUpdate(BaseModel):
    title: str


@app.put("/api/conversations/{conversation_id}")
def update_conversation(conversation_id: str, req: ConversationUpdate) -> dict:
    """修改对话标题。"""
    if not db.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    db.update_conversation(conversation_id, title=" ".join(req.title.split())[:60])
    return {"updated": True}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict:
    """删除对话（历史、每一轮、后台任务一起删除）。"""
    sessions.drop(conversation_id)
    jobs.cancel_queued(conversation_id)
    db.delete_conversation(conversation_id)
    return {"deleted": True}


@app.get("/api/conversations/{conversation_id}/turns")
def list_turns(conversation_id: str) -> list[dict]:
    """对话的每一轮（含模型文字、工具调用、后台任务状态），前端据此渲染。"""
    if not db.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    return conversation_turns(db, conversation_id)
