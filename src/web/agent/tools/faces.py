"""人脸检测，以及让用户在界面上选人脸 / 选角色。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from src.tools.person_detector import crop_faces

from .assets import describe_image, load_assets_json, save_asset_meta
from .base import IMAGE_EXTS, Tool, ToolContext, array, file_url, obj, register, string


def detect_faces_in_image(args: dict, ctx: ToolContext) -> dict:
    img_path = Path(args["image_path"])
    if not img_path.exists():
        return {"error": f"图片不存在: {args['image_path']}"}
    # 默认放进项目的 output/faces：素材库和 select_faces 都从这里读取
    default_dir = ctx.project_dir / "output" / "faces" if ctx.project_dir else img_path.parent / f"{img_path.stem}_faces"
    out_dir = Path(args.get("output_dir") or default_dir)
    crop_result = crop_faces(img_path, output_dir=out_dir)

    # 并发调用视觉模型给每张人脸命名
    paths = crop_result.cropped_paths
    descriptions: list[dict] = []
    if paths:
        with ThreadPoolExecutor(max_workers=len(paths)) as pool:
            descriptions = list(pool.map(lambda p: describe_image(p, ctx.lang), paths))

    face_list = []
    for i, face in enumerate(crop_result.faces_kept):
        crop_path = paths[i]
        desc = descriptions[i] if i < len(descriptions) else {"name": "person", "description": ""}
        save_asset_meta(crop_path, desc["name"], desc["description"])
        face_list.append({
            "index": i,
            "name": desc["name"],
            "description": desc["description"],
            "width": round(face.width, 1),
            "height": round(face.height, 1),
            "confidence": round(face.confidence, 3),
            "age": face.age,
            "gender": face.gender,
            "crop_path": str(crop_path),
        })
    return {
        "faces": face_list,
        "count": len(face_list),
        "skipped_small": crop_result.skipped_small,
        "skipped_blurry": crop_result.skipped_blurry,
        "original_image": str(img_path),
        "crop_directory": str(out_dir),
    }


def _image_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return [f for f in sorted(directory.iterdir()) if f.is_file() and f.suffix.lower() in IMAGE_EXTS]


def select_faces(args: dict, ctx: ToolContext) -> dict:
    """列出项目里已有的人脸，界面上让用户勾选要风格化的。"""
    faces_dir = ctx.project_dir / "output" / "faces" if ctx.project_dir else None
    face_list: list[dict] = []
    if faces_dir:
        meta = load_assets_json(faces_dir)
        for f in _image_files(faces_dir):
            file_meta = meta.get(f.name, {})
            face_list.append({
                "index": len(face_list),
                "name": file_meta.get("name", f.stem),
                "description": file_meta.get("description", ""),
                "age": None,
                "gender": None,
                "crop_path": str(f),
                "crop_url": file_url(f) or "",
            })
    if not face_list:
        return {"type": "face_select", "faces": [], "count": 0, "message": "项目里还没有人脸素材，请先上传照片并检测人脸。"}
    return {"type": "face_select", "faces": face_list, "count": len(face_list)}


def faces_selected(value: Any, display: dict) -> dict:
    """用户在人脸卡片里的选择 → 交给模型的结果。value: {"selected": [crop_path…]} 或 {"skipped": true}。"""
    value = value if isinstance(value, dict) else {}
    if value.get("skipped"):
        return {"skipped": True, "message": "用户跳过了风格化，不需要风格化任何人脸。"}
    chosen = set(value.get("selected") or [])
    faces = [f for f in display.get("faces") or [] if f.get("crop_path") in chosen]
    return {
        "selected": [{"name": f.get("name", ""), "path": f["crop_path"]} for f in faces],
        "message": "用户选好了要风格化的人脸：对每一张调用 stylize_character（face_path 用这里的 path）。",
    }


def select_characters(args: dict, ctx: ToolContext) -> dict:
    """列出项目里的角色和人脸素材，按模型的预选打勾，界面上让用户确认这次要用的角色。"""
    preselected = [item for item in args.get("preselected") or [] if isinstance(item, dict) and item.get("path")]
    labels = {item["path"]: item.get("label", "") for item in preselected}

    project_dir = ctx.project_dir
    if project_dir is None:
        # 没有项目目录时从预选路径推断（projects/{name}/output/…）
        for item in preselected:
            current = Path(item["path"]).parent
            for _ in range(5):
                if current.name == "output":
                    project_dir = current.parent
                    break
                current = current.parent
            if project_dir:
                break

    options: list[dict] = []
    if project_dir:
        for category, subdir in (("characters", project_dir / "output" / "stylized"), ("faces", project_dir / "output" / "faces")):
            meta = load_assets_json(subdir)
            for f in _image_files(subdir):
                file_meta = meta.get(f.name, {})
                option: dict[str, Any] = {
                    "path": str(f),
                    "url": file_url(f) or "",
                    "filename": f.name,
                    "category": category,
                    "name": file_meta.get("name", f.stem),
                    "description": file_meta.get("description", ""),
                    "selected": str(f) in labels,
                    "label": labels.get(str(f), ""),
                }
                if file_meta.get("source_face"):
                    option["source_face"] = file_meta["source_face"]
                options.append(option)
    if not options:
        return {"type": "character_select", "options": [], "message": "项目里还没有角色或人脸素材。"}
    return {"type": "character_select", "options": options, "preselected_count": len(preselected)}


def characters_selected(value: Any, display: dict) -> dict:
    """用户在角色卡片里的选择 → 交给模型的结果。value: {"selected": [{"path", "label"}…]}（按用户排好的顺序）。"""
    by_path = {o["path"]: o for o in display.get("options") or []}
    items = value.get("selected") if isinstance(value, dict) else None
    selected = []
    for item in items or []:
        path = item.get("path") if isinstance(item, dict) else item
        option = by_path.get(path)
        if option:
            label = (item.get("label") if isinstance(item, dict) else "") or option.get("label") or ""
            selected.append({"path": path, "name": option.get("name", ""), "label": label})
    return {
        "selected": selected,
        "message": "用户确认了这些角色：生成条漫时用它们的 path 作为角色图，label 是角色在剧本里的名字（没有 label 时用 name）。",
    }


register(
    Tool(
        name="detect_faces_in_image",
        description="检测图片中的所有人脸，返回人脸列表（bbox、age、gender）并裁剪保存。",
        parameters=obj({"image_path": string("图片路径"), "output_dir": string("裁剪输出目录（可选）")}, ["image_path"]),
        run=detect_faces_in_image,
        kind="write",
    ),
    Tool(
        name="select_faces",
        description=(
            "让用户从已检测的人脸中选择要风格化的人脸。"
            "当用户要求风格化角色时，必须先调用此工具让用户勾选要风格化哪些人脸。"
            "不要在人脸检测后自动调用，只在用户明确要求风格化时调用。"
        ),
        parameters=obj({}),
        run=select_faces,
        kind="interactive",
        on_input=faces_selected,
    ),
    Tool(
        name="select_characters",
        description=(
            "让用户从已有素材中选择角色。展示所有已风格化角色和人脸素材，"
            "自动预选最匹配用户描述的角色。用户可以自由调整选择后确认。"
            "在生成条漫前必须调用此工具让用户确认角色。"
        ),
        parameters=obj(
            {
                "preselected": array(
                    obj({"path": string("预选角色的文件路径"), "label": string("角色在剧本中的名字，如 Jules、Peize")}),
                    "根据用户描述预选的角色列表（path + label）",
                ),
            },
            ["preselected"],
        ),
        run=select_characters,
        kind="interactive",
        on_input=characters_selected,
    ),
)
