"""图片素材：看图命名、风格化角色、生成 / 编辑素材。生成类工具在后台执行（见 agent/jobs.py）。"""

from __future__ import annotations

import uuid
from pathlib import Path

from src.tools.face_stylizer import DEFAULT_PROMPT as CHARACTER_DESIGN_PROMPT
from src.tools.face_stylizer import stylize_face
from src.tools.gemini_image import edit_image, generate_image

from .assets import describe_image, find_stylized_dir, save_asset_meta
from .base import Tool, ToolContext, array, obj, register, string


def describe(args: dict, ctx: ToolContext) -> dict:
    img_path = Path(args["image_path"])
    if not img_path.exists():
        return {"error": f"图片不存在: {args['image_path']}"}
    desc = describe_image(img_path, ctx.lang)
    save_asset_meta(img_path, desc["name"], desc["description"])
    return {"name": desc["name"], "description": desc["description"], "image_path": str(img_path)}


def stylize_character(args: dict, ctx: ToolContext) -> dict:
    face_p = Path(args["face_path"])
    char_name = args.get("character_name", "character").replace(" ", "_")
    out_path = find_stylized_dir(face_p) / f"{char_name}_{uuid.uuid4().hex[:8]}.png"
    result_path = stylize_face(
        face_path=args["face_path"],
        output_path=out_path,
        original_image_path=args.get("original_image_path"),
        prompt=args.get("prompt"),
    )
    desc = describe_image(result_path, ctx.lang)
    save_asset_meta(result_path, desc["name"], desc["description"], source_face=face_p.name)
    return {
        "output_path": str(result_path), "character_name": desc["name"], "description": desc["description"],
        "source_face": face_p.name,
    }


def edit_asset(args: dict, ctx: ToolContext) -> dict:
    result_path = edit_image(image_path=args["image_path"], prompt=args["prompt"], output_path=args.get("output_path"))
    return {"output_path": str(result_path)}


_SCENE_PROMPT = (
    "Generate a 16:9 LANDSCAPE background scene image for animation/anime.\n\n"
    "ABSOLUTE REQUIREMENTS:\n"
    "- 16:9 widescreen aspect ratio (landscape orientation)\n"
    "- NO people, NO characters, NO figures — this is a PURE BACKGROUND/ENVIRONMENT only\n"
    "- Empty scene that will be used as a backdrop for character compositing\n"
    "- Anime/animation art style, detailed environment, cinematic lighting\n"
    "- Rich atmosphere and depth\n\n"
    "Scene description: {prompt}"
)


def generate_asset(args: dict, ctx: ToolContext) -> dict:
    out_path = Path(args["output_path"])
    prompt = args["prompt"]
    # 按输出目录自动加约束：scenes 优先（scenes/stylized 是场景目录，不是角色目录）
    is_scene = "scenes" in out_path.parts
    is_character = not is_scene and "stylized" in out_path.parts
    if is_scene:
        prompt = _SCENE_PROMPT.format(prompt=prompt)
    elif is_character:
        prompt = (
            CHARACTER_DESIGN_PROMPT.replace(
                "Transform this person's photo into an anime/illustration style FULL-BODY character design.",
                "Generate an anime/illustration style FULL-BODY character design from the description below.",
            )
            + f"\n\nCharacter description: {prompt}"
        )

    references = args.get("reference_images") or []
    result_path = generate_image(
        prompt=prompt,
        output_path=args["output_path"],
        reference_images=references or None,
        aspect_ratio="16:9" if is_scene else "9:16" if is_character else None,
    )
    desc = describe_image(result_path, ctx.lang)
    # 参考图来自 faces 目录时记下来源人脸
    source_face = next((Path(ref).name for ref in references if "faces" in Path(ref).parts), None)
    save_asset_meta(result_path, desc["name"], desc["description"], source_face=source_face)
    result = {"output_path": str(result_path), "name": desc["name"], "description": desc["description"]}
    if source_face:
        result["source_face"] = source_face
    return result


register(
    Tool(
        name="describe_image",
        description="用 VLM 分析图片，返回素材命名（snake_case英文）和中文描述。",
        parameters=obj({"image_path": string("图片路径")}, ["image_path"]),
        run=describe,
        kind="read",
    ),
    Tool(
        name="stylize_character",
        description="将人脸照片风格化为全身动画角色形象（9:16）。输入人脸裁剪图和原图。",
        parameters=obj(
            {
                "face_path": string("裁剪的人脸图片路径"),
                "character_name": string("角色特征简短描述，用于文件命名，如 yellow_jacket_boy、pink_dress_girl"),
                "original_image_path": string("原始完整图片路径（可选）"),
                "prompt": string("自定义风格化提示词（可选）"),
            },
            ["face_path", "character_name"],
        ),
        run=stylize_character,
        kind="generate",
    ),
    Tool(
        name="edit_asset",
        description="编辑已有图片素材（换服装、调整细节、去人等）。",
        parameters=obj(
            {"image_path": string("待编辑的图片路径"), "prompt": string("编辑指令"), "output_path": string("输出路径（可选）")},
            ["image_path", "prompt"],
        ),
        run=edit_asset,
        kind="generate",
    ),
    Tool(
        name="generate_asset",
        description=(
            "凭空生成新素材（新角色、新场景等）。输出到 stylized 目录会自动应用角色约束（9:16全身白底）；"
            "输出到 scenes 目录会自动应用场景约束（16:9横屏、空无一人的纯背景）。"
        ),
        parameters=obj(
            {
                "prompt": string("生成描述"),
                "output_path": string("输出路径"),
                "reference_images": array(string("图片路径"), "参考图片路径列表（可选）"),
            },
            ["prompt", "output_path"],
        ),
        run=generate_asset,
        kind="generate",
    ),
)
