"""人脸风格化工具 - 将真实人脸照片转为动画风格形象。

用法：
    from src.tools.face_stylizer import stylize_face

    result = stylize_face("input/photo.jpg", "output/anime.jpg")
"""

import logging
from pathlib import Path

from src.providers import image as image_provider

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = (
    "Transform this person's photo into an anime/illustration style FULL-BODY character design.\n\n"
    "ABSOLUTE REQUIREMENTS (violations = failure):\n"
    "1. FULL BODY: Show the COMPLETE figure from head to toe. Both feet/shoes MUST be fully visible. "
    "The soles of the shoes must be visible. NEVER crop at ankles, knees, or waist.\n"
    "2. COMPOSITION: Character occupies ~70% of image height. Leave 15% empty space above head "
    "and 15% below feet. The feet should be at the 85% mark, NOT at the bottom edge.\n"
    "3. BACKGROUND: Solid pure white (#FFFFFF). No gradients, no shadows on the ground, no objects, "
    "no scenery. ONLY flat white.\n"
    "4. ASPECT RATIO: 9:16 portrait.\n\n"
    "Style:\n"
    "- Clean anime/manga art, smooth cel shading, vibrant colors\n"
    "- Keep face features, hairstyle, and appearance recognizable from the reference\n"
    "- Maintain the same clothing, shoes, and accessories from the photo\n"
    "- Standing pose facing forward or slight 3/4 angle\n"
    "- Professional anime character design sheet quality\n\n"
    "Output a single image."
)


def stylize_face(
    face_path: str | Path,
    output_path: str | Path,
    original_image_path: str | Path | None = None,
    prompt: str | None = None,
    model: str | None = None,
    max_retries: int = 3,
) -> Path:
    """将真实人脸照片转为动画风格形象。

    Args:
        face_path: 裁剪的人脸照片路径。
        output_path: 输出风格化图片路径。
        original_image_path: 原始完整图片路径（提供服装、体型、姿态参考）。
        prompt: 自定义风格化提示词，None 使用默认动画风格。
        model: 临时覆盖配置里的图片模型（可选）。
        max_retries: 最大尝试次数。

    Returns:
        风格化后的图片路径。
    """
    face_path = Path(face_path)
    if not face_path.exists():
        raise FileNotFoundError(f"人脸图片不存在: {face_path}")

    # 参考图: 人脸图 + (原图)
    references: list[Path] = [face_path]
    if original_image_path is not None:
        original_image_path = Path(original_image_path)
        if not original_image_path.exists():
            raise FileNotFoundError(f"原图不存在: {original_image_path}")
        references.append(original_image_path)

    # 用户自定义 prompt 追加在默认要求之后，核心约束不可覆盖
    base_prompt = DEFAULT_PROMPT
    if prompt:
        base_prompt += f"\n\nAdditional instructions: {prompt}"
    if original_image_path is not None:
        base_prompt = (
            "Image 1: close-up face photo of the target person.\n"
            "Image 2: the original full scene photo — use it to reference this person's clothing, body type, and pose.\n\n"
            + base_prompt
        )

    result = image_provider.generate(
        base_prompt, references, aspect_ratio="9:16", model=model, max_retries=max_retries,
    )
    path = image_provider.save(result, output_path)
    logger.info(f"风格化图片已保存: {path}")
    return path
