"""剧本和文件：读写 md、列出目录、重命名素材。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from .assets import load_assets_json, write_assets_json
from .base import Tool, ToolContext, integer, obj, register, string


def read_script(args: dict, ctx: ToolContext) -> dict:
    p = Path(args["file_path"])
    if not p.exists():
        return {"error": f"文件不存在: {args['file_path']}"}
    return {"content": p.read_text(encoding="utf-8")}


def write_script(args: dict, ctx: ToolContext) -> dict:
    p = Path(args["file_path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args["content"], encoding="utf-8")
    return {"message": "写入成功", "file_path": str(p)}


def update_script(args: dict, ctx: ToolContext) -> dict:
    p = Path(args["file_path"])
    if not p.exists():
        return {"error": f"文件不存在: {args['file_path']}"}
    content = p.read_text(encoding="utf-8")
    if args["old_text"] not in content:
        return {"error": "未找到要替换的文本"}
    p.write_text(content.replace(args["old_text"], args["new_text"]), encoding="utf-8")
    return {"message": "替换成功"}


def list_files(args: dict, ctx: ToolContext) -> dict:
    directory = Path(args["directory"])
    if not directory.exists():
        return {"error": f"目录不存在: {args['directory']}"}
    if not directory.is_dir():
        return {"error": f"不是目录: {args['directory']}"}
    max_depth = int(args.get("max_depth", 2))
    files: list[str] = []
    assets_meta: dict[str, dict] = {}

    def walk(d: Path, depth: int, prefix: str = "") -> None:
        if depth > max_depth:
            return
        meta = load_assets_json(d)
        if meta:
            assets_meta[str(d.relative_to(directory)) if d != directory else "."] = meta
        try:
            entries = sorted(d.iterdir())
        except PermissionError:
            return
        for entry in entries:
            if entry.name == "assets.json":
                continue
            files.append(f"{prefix}{entry.name}{'/' if entry.is_dir() else ''}")
            if entry.is_dir():
                walk(entry, depth + 1, prefix + "  ")

    walk(directory, 1)
    result: dict = {"directory": str(directory), "files": files, "count": len(files)}
    if assets_meta:
        result["assets"] = assets_meta
    return result


def rename_asset(args: dict, ctx: ToolContext) -> dict:
    file_path = Path(args["file_path"])
    if not file_path.exists():
        return {"error": f"文件不存在: {args['file_path']}"}
    directory = file_path.parent
    old_filename = file_path.name
    data = load_assets_json(directory)
    entry = data.pop(old_filename, {})
    entry["name"] = args["name"]
    if args.get("description"):
        entry["description"] = args["description"]

    new_stem = args.get("filename") or args["name"]
    new_filename = new_stem + file_path.suffix
    new_path = directory / new_filename
    if new_path.exists() and new_path != file_path:
        new_filename = f"{new_stem}_{uuid.uuid4().hex[:6]}{file_path.suffix}"
        new_path = directory / new_filename
    file_path.rename(new_path)
    data[new_filename] = entry
    write_assets_json(directory, data)

    # 其他目录里引用了旧文件名的 source_face 一并更新
    if ctx.project_dir:
        for sub in (ctx.project_dir / "output").rglob("assets.json"):
            if sub.parent == directory:
                continue
            try:
                sub_data = json.loads(sub.read_text(encoding="utf-8"))
                changed = False
                for value in sub_data.values():
                    if isinstance(value, dict) and value.get("source_face") == old_filename:
                        value["source_face"] = new_filename
                        changed = True
                if changed:
                    write_assets_json(sub.parent, sub_data)
            except Exception:
                pass

    return {
        "message": f"已重命名为「{args['name']}」", "file_path": str(new_path), "name": args["name"],
        "old_filename": old_filename, "new_filename": new_filename,
    }


register(
    Tool(
        name="read_script",
        description="读取剧本 md 文件内容。",
        parameters=obj({"file_path": string("md 文件路径")}, ["file_path"]),
        run=read_script,
        kind="read",
    ),
    Tool(
        name="write_script",
        description="写入/覆盖剧本 md 文件。",
        parameters=obj({"file_path": string("md 文件路径"), "content": string("完整文件内容")}, ["file_path", "content"]),
        run=write_script,
        kind="write",
    ),
    Tool(
        name="update_script",
        description="替换剧本文件中的指定文本。",
        parameters=obj(
            {"file_path": string("md 文件路径"), "old_text": string("要替换的原文本"), "new_text": string("替换后的新文本")},
            ["file_path", "old_text", "new_text"],
        ),
        run=update_script,
        kind="write",
    ),
    Tool(
        name="list_files",
        description="列出指定目录下的文件和子目录（类似 tree 命令）。用于查看项目中已有的素材文件。",
        parameters=obj({"directory": string("要列出的目录路径"), "max_depth": integer("最大递归深度（默认2）")}, ["directory"]),
        run=list_files,
        kind="read",
    ),
    Tool(
        name="rename_asset",
        description=(
            "重命名素材：同时更新显示名称和文件名（保留扩展名）。"
            "当用户给角色或素材起名、备注、改名时调用此工具。"
            "文件名默认与 name 相同，也可通过 filename 参数单独指定。"
        ),
        parameters=obj(
            {
                "file_path": string("素材文件路径"),
                "name": string("新的显示名称"),
                "filename": string("新的文件名（不含扩展名，可选，默认用 name）"),
                "description": string("新的描述（可选，不传则保留原描述）"),
            },
            ["file_path", "name"],
        ),
        run=rename_asset,
        kind="write",
    ),
)
