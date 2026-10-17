"""工具的公共部分：声明格式、注册表、路径解析、执行。

每个工具 = 名称 + 说明 + 参数（JSON Schema）+ 执行函数，再加一个类型，决定它在各模式下怎么执行：
- read         只读，讨论模式也能用
- write        写文件（剧本、分镜草稿、重命名、人脸裁剪、画版式草图…），不用批准，直接执行
- generate     调用图片 / 视频模型，花钱：放到后台执行，立即返回 job_id（模型用 check_jobs 查结果）；
               「生成前确认」模式下要用户先批准
- interactive  在界面上让用户选择（选人脸 / 选角色）：用户选完，选择结果才作为工具结果交给模型
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[4]

KINDS = ("read", "write", "generate", "interactive")
MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".mp4", ".webm", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


class Cancelled(BaseException):
    """用户停止了任务。继承 BaseException：工具里的 except Exception 不会把它当成普通错误吞掉。"""


@dataclass
class ToolContext:
    """执行工具时的环境。jobs / cancel_event 只有 check_jobs 会用到；mode 决定能读哪些技能。"""

    project_dir: Path | None = None
    lang: str = "zh"
    mode: str = "comic"
    conversation_id: str | None = None
    turn_id: str | None = None
    jobs: Any = None
    cancel_event: threading.Event | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[[dict, ToolContext], dict]
    kind: str = "read"
    # 哪些创作模式提供这个工具
    modes: frozenset[str] = frozenset({"comic", "storyboard"})
    # generate 类：用哪种模型（并发数按这个用途的 Key 数量限制）
    role: str = "image"
    # interactive 类：把用户在卡片里的选择转换成交给模型的工具结果
    on_input: Callable[[Any, dict], dict] | None = None
    # 结果里的图片（output_path）附在下一次请求里给模型看（画草图后检查画得对不对）
    model_sees_output: bool = False

    @property
    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


# ========== 参数 Schema ==========

def string(description: str) -> dict:
    return {"type": "string", "description": description}


def integer(description: str) -> dict:
    return {"type": "integer", "description": description}


def boolean(description: str) -> dict:
    return {"type": "boolean", "description": description}


def array(items: dict, description: str) -> dict:
    return {"type": "array", "items": items, "description": description}


def obj(properties: dict, required: list[str] | None = None, description: str | None = None) -> dict:
    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    if description:
        schema["description"] = description
    return schema


# ========== 注册表 ==========

_TOOLS: dict[str, Tool] = {}


def register(*tools: Tool) -> None:
    for tool in tools:
        assert tool.kind in KINDS, tool.kind
        _TOOLS[tool.name] = tool


def get(name: str) -> Tool | None:
    return _TOOLS.get(name)


def for_mode(mode: str) -> list[Tool]:
    """某个创作模式下的全部工具（按注册顺序）。"""
    return [t for t in _TOOLS.values() if mode in t.modes]


# ========== 执行 ==========

_PATH_KEYS = (
    "image_path", "face_path", "output_path", "output_dir", "original_image_path",
    "file_path", "directory", "scene_path", "first_frame", "layout_path",
    "script_path", "draft_path", "strip_path", "previous_strip_path",
)
_PATH_LIST_KEYS = ("character_paths", "reference_images", "clip_paths", "drafts", "strips")


def resolve_path(p: str, project_dir: Path | None) -> str:
    """相对路径按项目目录解析成绝对路径。"""
    path = Path(p)
    if not path.is_absolute() and project_dir:
        path = project_dir / p
    return str(path)


def resolve_paths(args: dict, project_dir: Path | None) -> dict:
    """把参数里的文件路径都解析成绝对路径（模型经常传相对项目目录的路径）。"""
    out = dict(args)
    for key in _PATH_KEYS:
        if isinstance(out.get(key), str) and out[key]:
            out[key] = resolve_path(out[key], project_dir)
    for key in _PATH_LIST_KEYS:
        if isinstance(out.get(key), list):
            out[key] = [resolve_path(p, project_dir) if isinstance(p, str) else p for p in out[key]]
    if isinstance(out.get("preselected"), list):
        out["preselected"] = [
            {**item, "path": resolve_path(item["path"], project_dir)}
            if isinstance(item, dict) and isinstance(item.get("path"), str) and item["path"] else item
            for item in out["preselected"]
        ]
    return out


def execute(tool: Tool, args: dict, ctx: ToolContext) -> dict:
    """执行工具。漏传必填参数等异常作为工具错误返回给模型，不中断对话。"""
    resolved = resolve_paths(args, ctx.project_dir)
    logger.info(f"执行 tool: {tool.name}({json.dumps(resolved, ensure_ascii=False)[:200]})")
    try:
        result = tool.run(resolved, ctx)
    except Exception as exc:
        logger.exception(f"tool {tool.name} 执行出错")
        message = str(exc)
        # 漏传参数这类错误只有异常类型才看得懂（KeyError: 'face_path'）；服务商的报错本身就是完整的说明
        if not message or isinstance(exc, (KeyError, TypeError, AttributeError, IndexError)):
            message = f"{type(exc).__name__}: {message}"
        return {"error": message}
    return result if isinstance(result, dict) else {"result": result}


# ========== 文件 URL / 结果里的图片 ==========

def file_url(path: str | Path) -> str | None:
    """项目文件的访问地址（带 mtime 防缓存）；/files 只开放 projects/ 目录。"""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        rel = p.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return None
    if rel.parts[:1] != ("projects",):
        return None
    return f"/files/{rel.as_posix()}?v={int(p.stat().st_mtime)}"


def collect_media(tool_name: str, result: dict | None) -> list[dict]:
    """工具结果里产出的图片 / 视频，界面上展示用。"""
    if not isinstance(result, dict):
        return []
    paths: list[str] = []
    for key in ("first_frame", "strip_path"):
        if isinstance(result.get(key), str):
            paths.append(result[key])
    for key in ("frames", "faces"):
        for item in result.get(key) or []:
            path = item.get("crop_path") if isinstance(item, dict) else item
            if isinstance(path, str):
                paths.append(path)
    if isinstance(result.get("output_path"), str):
        paths.append(result["output_path"])

    media = []
    for path in dict.fromkeys(paths):
        if Path(path).suffix.lower() not in MEDIA_EXTS:
            continue
        url = file_url(path)
        if url:
            media.append({"path": str(path), "url": url, "tool": tool_name})
    return media


def has_choices(result: dict) -> bool:
    """interactive 工具有没有给出可选的内容；没有时（例如项目里还没有人脸）直接把结果交给模型。"""
    return isinstance(result, dict) and not result.get("error") and bool(result.get("options") or result.get("faces"))
