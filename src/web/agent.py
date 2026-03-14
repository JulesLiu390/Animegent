"""对话 Agent - 基于 Gemini function calling 编排 AniDaily tools。"""

import json
import logging
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

from google.genai.types import (
    Content,
    FunctionCallingConfig,
    FunctionCallingConfigMode,
    FunctionDeclaration,
    GenerateContentConfig,
    Part,
    Schema,
    ToolConfig,
    Type,
)

from src.tools.face_stylizer import stylize_face
from src.tools.gemini_image import edit_image, generate_image
from src.tools.models.registry import get_genai_client
from src.tools.person_detector import crop_faces

logger = logging.getLogger(__name__)

MODEL = "gemini-3-flash-preview"
PROJECT_ROOT = Path(__file__).parent.parent.parent

# ========== Tool 定义 ==========

TOOL_DECLARATIONS = [
    FunctionDeclaration(
        name="detect_faces_in_image",
        description="检测图片中的所有人脸，返回人脸列表（bbox、age、gender）并裁剪保存。",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "image_path": Schema(type=Type.STRING, description="图片路径"),
                "output_dir": Schema(type=Type.STRING, description="裁剪输出目录（可选）"),
            },
            required=["image_path"],
        ),
    ),
    FunctionDeclaration(
        name="stylize_character",
        description="将人脸照片风格化为全身动画角色形象（9:16）。输入人脸裁剪图和原图。",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "face_path": Schema(type=Type.STRING, description="裁剪的人脸图片路径"),
                "character_name": Schema(type=Type.STRING, description="角色特征简短描述，用于文件命名，如 yellow_jacket_boy、pink_dress_girl"),
                "original_image_path": Schema(type=Type.STRING, description="原始完整图片路径（可选）"),
                "prompt": Schema(type=Type.STRING, description="自定义风格化提示词（可选）"),
            },
            required=["face_path", "character_name"],
        ),
    ),
    FunctionDeclaration(
        name="edit_asset",
        description="编辑已有图片素材（换服装、调整细节、去人等）。",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "image_path": Schema(type=Type.STRING, description="待编辑的图片路径"),
                "prompt": Schema(type=Type.STRING, description="编辑指令"),
                "output_path": Schema(type=Type.STRING, description="输出路径（可选）"),
            },
            required=["image_path", "prompt"],
        ),
    ),
    FunctionDeclaration(
        name="generate_asset",
        description="凭空生成新素材（新角色、新场景等）。生成角色时请输出到 stylized 目录，会自动应用角色设计约束（9:16全身白底彩色动画风）。",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "prompt": Schema(type=Type.STRING, description="生成描述"),
                "output_path": Schema(type=Type.STRING, description="输出路径"),
                "reference_images": Schema(
                    type=Type.ARRAY,
                    items=Schema(type=Type.STRING),
                    description="参考图片路径列表（可选）",
                ),
            },
            required=["prompt", "output_path"],
        ),
    ),
    FunctionDeclaration(
        name="generate_comic_strip",
        description=(
            "生成一条竖向条漫（4-6格）。每次调用生成一条，可多次调用生成多条。"
            "必须传入角色素材图片路径（stylized目录下）和本条的剧本内容。"
            "输出一张 9:16 竖向条漫图片，包含分格、对话气泡和黑色分格边框。"
        ),
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "character_paths": Schema(
                    type=Type.ARRAY,
                    items=Schema(type=Type.STRING),
                    description="角色图片路径列表（必须是 stylized 目录下的角色图）",
                ),
                "character_names": Schema(
                    type=Type.ARRAY,
                    items=Schema(type=Type.STRING),
                    description="角色名称列表，与 character_paths 一一对应，如 ['Jules', 'Peize']",
                ),
                "script": Schema(type=Type.STRING, description="本条条漫的剧本（4-6格的分格描述、对话、镜头）"),
                "strip_index": Schema(type=Type.INTEGER, description="条漫编号，从1开始"),
                "output_path": Schema(type=Type.STRING, description="输出路径"),
                "scene_path": Schema(type=Type.STRING, description="场景/背景参考图路径（可选）"),
            },
            required=["character_paths", "character_names", "script", "strip_index", "output_path"],
        ),
    ),
    FunctionDeclaration(
        name="read_script",
        description="读取剧本 md 文件内容。",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "file_path": Schema(type=Type.STRING, description="md 文件路径"),
            },
            required=["file_path"],
        ),
    ),
    FunctionDeclaration(
        name="write_script",
        description="写入/覆盖剧本 md 文件。",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "file_path": Schema(type=Type.STRING, description="md 文件路径"),
                "content": Schema(type=Type.STRING, description="完整文件内容"),
            },
            required=["file_path", "content"],
        ),
    ),
    FunctionDeclaration(
        name="update_script",
        description="替换剧本文件中的指定文本。",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "file_path": Schema(type=Type.STRING, description="md 文件路径"),
                "old_text": Schema(type=Type.STRING, description="要替换的原文本"),
                "new_text": Schema(type=Type.STRING, description="替换后的新文本"),
            },
            required=["file_path", "old_text", "new_text"],
        ),
    ),
    FunctionDeclaration(
        name="describe_image",
        description="用 VLM 分析图片，返回素材命名（snake_case英文）和中文描述。",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "image_path": Schema(type=Type.STRING, description="图片路径"),
            },
            required=["image_path"],
        ),
    ),
    FunctionDeclaration(
        name="list_files",
        description="列出指定目录下的文件和子目录（类似 tree 命令）。用于查看项目中已有的素材文件。",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "directory": Schema(type=Type.STRING, description="要列出的目录路径"),
                "max_depth": Schema(type=Type.INTEGER, description="最大递归深度（默认2）"),
            },
            required=["directory"],
        ),
    ),
    FunctionDeclaration(
        name="select_characters",
        description=(
            "让用户从已有素材中选择角色。展示所有已风格化角色和人脸素材，"
            "自动预选最匹配用户描述的角色。用户可以自由调整选择后确认。"
            "在生成条漫前必须调用此工具让用户确认角色。"
        ),
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "preselected": Schema(
                    type=Type.ARRAY,
                    items=Schema(
                        type=Type.OBJECT,
                        properties={
                            "path": Schema(type=Type.STRING, description="预选角色的文件路径"),
                            "label": Schema(type=Type.STRING, description="角色在剧本中的名字，如 Jules、Peize"),
                        },
                    ),
                    description="根据用户描述预选的角色列表（path + label）",
                ),
            },
            required=["preselected"],
        ),
    ),
]


# ========== Tool 执行 ==========

def _load_assets_json(directory: Path) -> dict:
    """读取目录下的 assets.json。"""
    p = directory / "assets.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_asset_meta(file_path: Path, name: str, description: str) -> None:
    """将素材的 name/description 写入所在目录的 assets.json。"""
    directory = file_path.parent
    data = _load_assets_json(directory)
    data[file_path.name] = {"name": name, "description": description}
    (directory / "assets.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


DESCRIBE_MODEL = "gemini-2.5-flash-lite"
DESCRIBE_PROMPT = (
    'Analyze this image and respond with a JSON object containing exactly two fields:\n'
    '1. "name": a short snake_case name for this asset (max 4 words), suitable as a filename. '
    'Focus on the most distinctive visual features: clothing color/type, hair, accessories, scene type.\n'
    '   Examples: yellow_jacket_boy, pink_dress_girl, sunset_beach_scene, dark_alley\n'
    '2. "description": a concise one-sentence description of what is in the image (in Chinese).\n\n'
    'Output ONLY valid JSON, no markdown, no extra text.\n'
    'Example: {"name": "yellow_jacket_boy", "description": "穿黄色夹克的年轻男性，短发，双手交叉"}'
)


def _describe_image(image_path: Path) -> dict:
    """用 VLM 生成图片的名称和描述。

    Returns:
        {"name": "snake_case_name", "description": "中文描述"}
    """
    try:
        from google.genai.types import GenerateContentConfig, Part

        client = get_genai_client(timeout=30_000)
        suffix = image_path.suffix.lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix, "image/jpeg")
        img_part = Part.from_bytes(data=image_path.read_bytes(), mime_type=mime)
        resp = client.models.generate_content(
            model=DESCRIBE_MODEL,
            contents=[img_part, DESCRIBE_PROMPT],
            config=GenerateContentConfig(temperature=0.0),
        )
        text = resp.text.strip()
        # 去掉可能的 markdown 代码块
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
        name = data.get("name", "asset")
        name = name.lower().replace(" ", "_").replace("-", "_")
        name = "".join(c for c in name if c.isalnum() or c == "_").strip("_")
        return {
            "name": name[:40] if name else "asset",
            "description": data.get("description", ""),
        }
    except Exception as e:
        logger.warning(f"VLM 描述失败: {e}")
    return {"name": "asset", "description": ""}


def _find_stylized_dir(face_path: Path) -> Path:
    """从人脸路径推断项目的 stylized 输出目录。"""
    # 人脸通常在 projects/{name}/output/faces/ 下
    # 往上找到 output 目录，然后定位 stylized
    current = face_path.parent
    for _ in range(5):
        if current.name == "output":
            d = current / "stylized"
            d.mkdir(parents=True, exist_ok=True)
            return d
        if current.name == "faces" and current.parent.name == "output":
            d = current.parent / "stylized"
            d.mkdir(parents=True, exist_ok=True)
            return d
        current = current.parent
    # fallback: 同目录
    return face_path.parent


def _resolve_path(p: str, project_dir: Path | None) -> str:
    """将相对路径解析为绝对路径（基于项目目录）。"""
    path = Path(p)
    if not path.is_absolute() and project_dir:
        path = project_dir / p
    return str(path)


def _execute_tool(name: str, args: dict, project_dir: Path | None = None) -> dict:
    """执行指定 tool 并返回结果。"""
    # 自动将常见路径参数解析为绝对路径
    PATH_KEYS = [
        "image_path", "face_path", "output_path", "original_image_path",
        "file_path", "directory", "scene_path",
    ]
    for key in PATH_KEYS:
        if key in args and args[key] and not Path(args[key]).is_absolute():
            args[key] = _resolve_path(args[key], project_dir)
    # 列表类型路径参数
    for key in ["character_paths", "reference_images"]:
        if key in args and isinstance(args[key], list):
            args[key] = [_resolve_path(p, project_dir) if not Path(p).is_absolute() else p for p in args[key]]

    logger.info(f"执行 tool: {name}({json.dumps(args, ensure_ascii=False)[:200]})")

    if name == "detect_faces_in_image":
        from concurrent.futures import ThreadPoolExecutor, as_completed

        img_path = Path(args["image_path"])
        if not img_path.exists():
            return {"error": f"图片不存在: {args['image_path']}"}
        out_dir = Path(args.get("output_dir") or str(img_path.parent / f"{img_path.stem}_faces"))
        crop_result = crop_faces(img_path, output_dir=out_dir)

        # 并发调用 VLM 描述每个人脸
        descriptions: dict[int, dict] = {}
        if crop_result.cropped_paths:
            with ThreadPoolExecutor(max_workers=len(crop_result.cropped_paths)) as pool:
                futures = {
                    pool.submit(_describe_image, cp): i
                    for i, cp in enumerate(crop_result.cropped_paths)
                }
                for fut in as_completed(futures):
                    idx = futures[fut]
                    descriptions[idx] = fut.result()

        face_list = []
        for i, face in enumerate(crop_result.faces_kept):
            crop_path = crop_result.cropped_paths[i]
            desc = descriptions.get(i, {"name": "person", "description": ""})
            _save_asset_meta(crop_path, desc["name"], desc["description"])
            info = {
                "index": i,
                "name": desc["name"],
                "description": desc["description"],
                "width": round(face.width, 1),
                "height": round(face.height, 1),
                "confidence": round(face.confidence, 3),
                "age": face.age,
                "gender": face.gender,
                "crop_path": str(crop_path),
            }
            face_list.append(info)
        return {
            "faces": face_list,
            "count": len(face_list),
            "skipped_small": crop_result.skipped_small,
            "skipped_blurry": crop_result.skipped_blurry,
            "original_image": str(img_path),
            "crop_directory": str(out_dir),
        }

    elif name == "stylize_character":
        try:
            import uuid as _uuid
            char_name = args.get("character_name", "character").replace(" ", "_")
            uid = _uuid.uuid4().hex[:8]
            # 输出到项目的 stylized 目录
            face_p = Path(args["face_path"])
            # 向上找 output/stylized 目录
            stylized_dir = _find_stylized_dir(face_p)
            out_path = stylized_dir / f"{char_name}_{uid}.png"
            result_path = stylize_face(
                face_path=args["face_path"],
                output_path=out_path,
                original_image_path=args.get("original_image_path"),
                prompt=args.get("prompt"),
            )
            # VLM 描述风格化后的角色
            desc = _describe_image(result_path)
            _save_asset_meta(result_path, desc["name"], desc["description"])
            return {"output_path": str(result_path), "character_name": desc["name"], "description": desc["description"]}
        except Exception as e:
            return {"error": str(e)}

    elif name == "edit_asset":
        try:
            result_path = edit_image(
                image_path=args["image_path"],
                prompt=args["prompt"],
                output_path=args.get("output_path"),
            )
            return {"output_path": str(result_path)}
        except Exception as e:
            return {"error": str(e)}

    elif name == "generate_asset":
        try:
            from src.tools.face_stylizer import DEFAULT_PROMPT as CHARACTER_DESIGN_PROMPT

            out_path = Path(args["output_path"])
            prompt = args["prompt"]

            # 如果输出到 stylized 目录，自动注入角色设计约束（9:16、全身、白色背景、彩色）
            is_character = "stylized" in out_path.parts
            if is_character:
                prompt = (
                    CHARACTER_DESIGN_PROMPT.replace(
                        "Transform this person's photo into an anime/illustration style FULL-BODY character design.",
                        "Generate an anime/illustration style FULL-BODY character design from the description below.",
                    )
                    + f"\n\nCharacter description: {prompt}"
                )

            result_path = generate_image(
                prompt=prompt,
                output_path=args["output_path"],
                reference_images=args.get("reference_images"),
            )
            # VLM 描述生成的素材
            desc = _describe_image(result_path)
            _save_asset_meta(result_path, desc["name"], desc["description"])
            return {
                "output_path": str(result_path),
                "name": desc["name"],
                "description": desc["description"],
            }
        except Exception as e:
            return {"error": str(e)}

    elif name == "generate_comic_strip":
        from src.mcp_tools.generate_panel import _guess_mime
        from google.genai.types import GenerateContentConfig as GCC

        char_paths = args["character_paths"]
        char_names = args.get("character_names", [])
        script = args["script"]
        strip_index = int(args.get("strip_index", 1))

        contents: list = []
        char_labels = []
        for i, cp in enumerate(char_paths):
            p = Path(cp)
            if not p.exists():
                return {"error": f"角色图不存在: {cp}"}
            contents.append(Part.from_bytes(data=p.read_bytes(), mime_type=_guess_mime(p)))
            name_label = char_names[i] if i < len(char_names) else chr(ord("A") + i)
            char_labels.append(f"Image {i + 1}: Character {name_label}")

        scene_label = ""
        if args.get("scene_path"):
            sp = Path(args["scene_path"])
            if not sp.exists():
                return {"error": f"场景图不存在: {args['scene_path']}"}
            contents.append(Part.from_bytes(data=sp.read_bytes(), mime_type=_guess_mime(sp)))
            scene_label = f"Image {len(char_paths) + 1}: Scene/Background\n"

        prompt = (
            f"{chr(10).join(char_labels)}\n{scene_label}\n"
            f"Generate a vertical comic strip (条漫) with 4-6 panels.\n"
            f"This is strip #{strip_index}. Script for this strip:\n\n"
            f"{script}\n\n"
            f"STRICT RULES:\n"
            f"1. ONLY draw the characters shown above. Do NOT invent or add ANY other characters.\n"
            f"2. Each character's appearance MUST match their reference image exactly.\n"
            f"3. Every named character in the script should appear in at least 2 panels.\n\n"
            f"FORMAT:\n"
            f"- Vertical layout, 9:16 aspect ratio\n"
            f"- Black panel borders separating each panel\n"
            f"- Manga/comic art style\n"
            f"- Dialogue bubbles in Chinese\n"
            f"- Vary camera angles across panels (wide, medium, close-up)\n\n"
            f"Output a single vertical comic strip image."
        )
        contents.append(prompt)

        try:
            client = get_genai_client()
            resp = client.models.generate_content(
                model="gemini-3.1-flash-image-preview",
                contents=contents,
                config=GCC(response_modalities=["IMAGE", "TEXT"]),
            )
            image_bytes = None
            text_response = None
            if resp.candidates:
                for part in resp.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                        image_bytes = part.inline_data.data
                    if part.text:
                        text_response = part.text
            if not image_bytes:
                return {"error": "未返回图片", "text": text_response}
            out = Path(args["output_path"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(image_bytes)
            result_dict: dict = {
                "output_path": str(out),
                "strip_index": strip_index,
                "characters": char_paths,
            }
            if text_response:
                result_dict["text"] = text_response
            return result_dict
        except Exception as e:
            return {"error": str(e)}

    elif name == "describe_image":
        img_path = Path(args["image_path"])
        if not img_path.exists():
            return {"error": f"图片不存在: {args['image_path']}"}
        desc = _describe_image(img_path)
        _save_asset_meta(img_path, desc["name"], desc["description"])
        return {"name": desc["name"], "description": desc["description"], "image_path": str(img_path)}

    elif name == "read_script":
        p = Path(args["file_path"])
        if not p.exists():
            return {"error": f"文件不存在: {args['file_path']}"}
        return {"content": p.read_text(encoding="utf-8")}

    elif name == "write_script":
        p = Path(args["file_path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"], encoding="utf-8")
        return {"message": "写入成功", "file_path": str(p)}

    elif name == "update_script":
        p = Path(args["file_path"])
        if not p.exists():
            return {"error": f"文件不存在: {args['file_path']}"}
        content = p.read_text(encoding="utf-8")
        if args["old_text"] not in content:
            return {"error": "未找到要替换的文本"}
        new_content = content.replace(args["old_text"], args["new_text"])
        p.write_text(new_content, encoding="utf-8")
        return {"message": "替换成功"}

    elif name == "list_files":
        directory = Path(args["directory"])
        if not directory.exists():
            return {"error": f"目录不存在: {args['directory']}"}
        if not directory.is_dir():
            return {"error": f"不是目录: {args['directory']}"}
        max_depth = int(args.get("max_depth", 2))
        files: list[str] = []
        assets_meta: dict[str, dict] = {}

        def _walk(d: Path, depth: int, prefix: str = ""):
            if depth > max_depth:
                return
            # 读取该目录的 assets.json
            meta = _load_assets_json(d)
            if meta:
                rel = str(d.relative_to(directory)) if d != directory else "."
                assets_meta[rel] = meta
            try:
                entries = sorted(d.iterdir())
            except PermissionError:
                return
            for entry in entries:
                if entry.name == "assets.json":
                    continue  # 不列出 assets.json 本身
                files.append(f"{prefix}{entry.name}{'/' if entry.is_dir() else ''}")
                if entry.is_dir():
                    _walk(entry, depth + 1, prefix + "  ")

        _walk(directory, 1)
        result: dict = {"directory": str(directory), "files": files, "count": len(files)}
        if assets_meta:
            result["assets"] = assets_meta
        return result

    elif name == "select_characters":
        preselected = args.get("preselected", [])
        preselected_paths = {item["path"] for item in preselected}
        preselected_labels = {item["path"]: item.get("label", "") for item in preselected}

        all_options: list[dict] = []

        # 从 preselected 路径推断项目目录
        project_dir = None
        for item in preselected:
            p = Path(item["path"])
            current = p.parent
            for _ in range(5):
                if current.name == "output":
                    project_dir = current.parent
                    break
                current = current.parent
            if project_dir:
                break

        SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}
        if project_dir:
            for category, subdir in [
                ("characters", project_dir / "output" / "stylized"),
                ("faces", project_dir / "output" / "faces"),
            ]:
                if not subdir.exists():
                    continue
                meta = _load_assets_json(subdir)
                for f in sorted(subdir.iterdir()):
                    if not f.is_file() or f.suffix.lower() not in SUPPORTED:
                        continue
                    file_meta = meta.get(f.name, {})
                    rel = f.relative_to(PROJECT_ROOT)
                    option = {
                        "path": str(f),
                        "url": f"/files/{rel}",
                        "filename": f.name,
                        "category": category,
                        "name": file_meta.get("name", f.stem),
                        "description": file_meta.get("description", ""),
                        "selected": str(f) in preselected_paths,
                        "label": preselected_labels.get(str(f), ""),
                    }
                    all_options.append(option)

        return {
            "type": "character_select",
            "options": all_options,
            "preselected_count": len(preselected),
        }

    else:
        return {"error": f"未知 tool: {name}"}


# ========== Agent ==========

SYSTEM_INSTRUCTION_TEMPLATE = (
    "你是 AniDaily 动画条漫生成助手。你可以：\n"
    "1. 检测图片中的人脸并风格化为动画角色\n"
    "2. 编辑已有素材或凭空生成新素材\n"
    "3. 分析场景\n"
    "4. 生成竖向条漫（4-6格）\n"
    "5. 读写剧本 md 文件\n\n"
    "交互规则：\n"
    "- 当用户发送图片时，不要自动执行任何工具。先确认用户的意图（例如：检测人脸？风格化角色？编辑素材？），"
    "然后再执行对应操作。\n"
    "- 只有当用户明确要求执行某个操作时，才调用对应工具。\n"
    "- 人脸检测完成后，如果检测到人脸，**必须先向用户展示检测结果**（每个人脸的编号、年龄、性别等信息），"
    "然后询问用户是否要对这些人脸进行风格化，以及要风格化哪些人（例如「全部」或「只要第1和第3个」）。"
    "**绝对不要在检测后自动调用 stylize_character**，必须等用户确认。\n"
    "- 工具返回的文件路径必须在后续操作中直接使用，不要猜测路径。\n"
    "- 如果不确定文件位置，先使用 list_files 工具查看。\n"
    "- **生成条漫的工作流**：\n"
    "  1. 先用 list_files 查看 output/stylized/ 目录，了解已有角色。\n"
    "  2. 调用 select_characters，根据用户描述预选最匹配的角色（preselected 里填 path+label）。\n"
    "     用户会在前端交互式选择确认。\n"
    "  3. 用户确认角色后，写剧本（write_script），按条划分（每条4-6格）。\n"
    "  4. 把剧本展示给用户，询问：要生成几条条漫？默认1条。\n"
    "  5. 用户确认后，对每条调用一次 generate_comic_strip，传入用户确认的角色路径。\n"
    "  6. 绝对不要用 generate_asset 生成条漫，generate_asset 不支持角色参考图。\n\n"
    "{project_context}"
    "回复使用中文。"
)


class Agent:
    """对话 Agent，维护多轮对话历史，通过 Gemini function calling 调用 tools。"""

    def __init__(self, project_dir: Path | None = None):
        self.history: list[Content] = []
        self.project_dir = project_dir

    def _build_system_instruction(self) -> str:
        if self.project_dir:
            out = self.project_dir / "output"
            project_context = (
                f"当前项目目录: {self.project_dir}\n"
                f"用户上传的原始图片在 {self.project_dir / 'input'}/ 下。\n"
                f"输出文件必须放在对应子目录下：\n"
                f"  - 风格化角色: {out / 'stylized'}/\n"
                f"  - 人脸裁剪: {out / 'faces'}/\n"
                f"  - 场景: {out / 'scenes' / 'stylized'}/\n"
                f"  - 去人场景: {out / 'scenes' / 'no_people'}/\n"
                f"  - 条漫: {out / 'panels'}/\n"
                f"  - 剧本: {out / 'scripts'}/\n\n"
            )
            # 自动注入各分类已有素材
            asset_summary = self._build_asset_summary()
            if asset_summary:
                project_context += f"当前项目已有素材：\n{asset_summary}\n"
        else:
            project_context = "所有文件路径基于项目根目录。输出文件默认放在 output/ 下。\n"
        return SYSTEM_INSTRUCTION_TEMPLATE.format(project_context=project_context)

    def _build_asset_summary(self) -> str:
        """读取项目各分类的 assets.json，生成素材摘要注入到 system instruction。"""
        if not self.project_dir:
            return ""
        out = self.project_dir / "output"
        categories = {
            "原始图片": self.project_dir / "input",
            "风格化角色": out / "stylized",
            "人脸": out / "faces",
            "场景": out / "scenes" / "stylized",
            "去人场景": out / "scenes" / "no_people",
            "条漫": out / "panels",
            "剧本": out / "scripts",
        }
        lines: list[str] = []
        for label, dir_path in categories.items():
            if not dir_path.exists():
                continue
            meta = _load_assets_json(dir_path)
            # 统计目录中的实际文件（排除 assets.json）
            files = [f for f in dir_path.iterdir() if f.is_file() and f.name != "assets.json"]
            if not files:
                continue
            if meta:
                items = []
                for f in files:
                    info = meta.get(f.name)
                    if info:
                        items.append(f"    - {f.name}: {info.get('name', '')} ({info.get('description', '')})")
                    else:
                        items.append(f"    - {f.name}")
                lines.append(f"  [{label}] ({len(files)} 个):")
                lines.extend(items)
            else:
                lines.append(f"  [{label}] ({len(files)} 个): {', '.join(f.name for f in files[:5])}")
                if len(files) > 5:
                    lines.append(f"    ... 等共 {len(files)} 个文件")
        return "\n".join(lines)

    def _build_config(self) -> GenerateContentConfig:
        return GenerateContentConfig(
            system_instruction=self._build_system_instruction(),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            tool_config=ToolConfig(
                function_calling_config=FunctionCallingConfig(
                    mode=FunctionCallingConfigMode.AUTO,
                ),
            ),
        )

    def chat_stream(
        self, message: str, image_paths: list[str] | None = None
    ) -> Generator[dict, None, None]:
        """处理一轮对话，流式返回事件。

        事件类型:
        - text_delta: {"event": "text_delta", "delta": str}
        - tool_start:  {"event": "tool_start", "tool": str, "args": dict, "index": int}
        - tool_end:    {"event": "tool_end", "tool": str, "result": dict, "duration_ms": int, "index": int, "images": list|None}
        - done:        {"event": "done"}
        """
        # 构建用户消息
        user_parts: list = []
        if image_paths:
            for img_path in image_paths:
                p = Path(img_path)
                if p.exists():
                    suffix = p.suffix.lower()
                    mime = {
                        ".png": "image/png", ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg", ".webp": "image/webp",
                    }.get(suffix, "application/octet-stream")
                    user_parts.append(Part.from_text(text=f"[图片路径: {p}]"))
                    user_parts.append(Part.from_bytes(data=p.read_bytes(), mime_type=mime))
        user_parts.append(Part.from_text(text=message))
        self.history.append(Content(role="user", parts=user_parts))

        config = self._build_config()
        tool_index = 0
        max_rounds = 10

        for _ in range(max_rounds):
            client = get_genai_client(timeout=180_000)

            # 流式调用 Gemini
            accumulated_text = ""
            accumulated_parts: list[Part] = []
            function_call_parts: list = []

            stream = client.models.generate_content_stream(
                model=MODEL,
                contents=self.history,
                config=config,
            )

            for chunk in stream:
                if not chunk.candidates:
                    continue
                for part in chunk.candidates[0].content.parts:
                    if part.function_call is not None:
                        function_call_parts.append(part)
                    elif part.text:
                        accumulated_text += part.text
                        yield {"event": "text_delta", "delta": part.text}

            # 构建完整的 content 并加入历史
            all_parts = []
            if accumulated_text:
                all_parts.append(Part.from_text(text=accumulated_text))
            all_parts.extend(function_call_parts)

            if all_parts:
                self.history.append(Content(role="model", parts=all_parts))

            if not function_call_parts:
                # 没有 function call，结束
                break

            # 执行 function calls
            function_response_parts = []
            for fc_part in function_call_parts:
                fc = fc_part.function_call
                tool_name = fc.name
                tool_args = dict(fc.args) if fc.args else {}

                yield {"event": "tool_start", "tool": tool_name, "args": tool_args, "index": tool_index}

                t0 = time.time()
                result = _execute_tool(tool_name, tool_args, project_dir=self.project_dir)
                duration_ms = round((time.time() - t0) * 1000)

                # 收集生成的图片
                images = None
                if "output_path" in result:
                    out_path = Path(result["output_path"])
                    if out_path.exists():
                        rel = out_path.relative_to(PROJECT_ROOT)
                        images = [{"path": str(out_path), "url": f"/files/{rel}", "tool": tool_name}]
                # detect_faces 返回多张裁剪图
                if "faces" in result and isinstance(result["faces"], list):
                    face_images = []
                    for face_info in result["faces"]:
                        cp = face_info.get("crop_path")
                        if cp:
                            cp_path = Path(cp)
                            if cp_path.exists():
                                rel = cp_path.relative_to(PROJECT_ROOT)
                                face_images.append({"path": cp, "url": f"/files/{rel}", "tool": tool_name})
                    if face_images:
                        images = (images or []) + face_images

                yield {
                    "event": "tool_end",
                    "tool": tool_name,
                    "result": result,
                    "duration_ms": duration_ms,
                    "index": tool_index,
                    "images": images,
                }

                tool_index += 1

                function_response_parts.append(
                    Part.from_function_response(name=tool_name, response=result)
                )

            self.history.append(Content(role="user", parts=function_response_parts))

        yield {"event": "done"}
