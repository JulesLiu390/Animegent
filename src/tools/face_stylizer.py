"""人脸风格化工具 - 将真实人脸照片转为动画风格形象。

用法：
    from src.tools.face_stylizer import stylize_face

    result = stylize_face("input/photo.jpg", "output/anime.jpg")
"""

import logging
from pathlib import Path

from google.genai.types import GenerateContentConfig, Part

from src.tools.models.registry import get_genai_client

logger = logging.getLogger(__name__)

IMAGE_MODEL = "gemini-3.1-flash-image-preview"

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
    model: str = IMAGE_MODEL,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> Path:
    """将真实人脸照片转为动画风格形象。

    Args:
        face_path: 裁剪的人脸照片路径。
        output_path: 输出风格化图片路径。
        original_image_path: 原始完整图片路径（提供服装、体型、姿态参考）。
        prompt: 自定义风格化提示词，None 使用默认动画风格。
        model: 图像生成模型 ID。
        max_retries: 最大重试次数。
        retry_delay: 重试间隔（秒），每次翻倍。

    Returns:
        风格化后的图片路径。
    """
    import time

    face_path = Path(face_path)
    output_path = Path(output_path)

    if not face_path.exists():
        raise FileNotFoundError(f"人脸图片不存在: {face_path}")

    # 构建 contents: 人脸图 + (原图) + prompt
    contents: list = []

    face_part = Part.from_bytes(data=face_path.read_bytes(), mime_type=_guess_mime(face_path))
    contents.append(face_part)

    if original_image_path is not None:
        original_image_path = Path(original_image_path)
        if not original_image_path.exists():
            raise FileNotFoundError(f"原图不存在: {original_image_path}")
        original_part = Part.from_bytes(
            data=original_image_path.read_bytes(), mime_type=_guess_mime(original_image_path)
        )
        contents.append(original_part)

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
    contents.append(base_prompt)

    last_error: Exception | None = None
    delay = retry_delay
    for attempt in range(1, max_retries + 1):
        client = get_genai_client()
        try:
            resp = client.models.generate_content(
                model=model,
                contents=contents,
                config=GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )
            image_bytes = _extract_image_from_response(resp)
            if image_bytes is None:
                raise RuntimeError("Gemini 未返回图片")

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(image_bytes)
            logger.info(f"风格化图片已保存: {output_path}")
            return output_path
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                logger.warning(f"风格化重试 {attempt}/{max_retries}: {e}")
                time.sleep(delay)
                delay = min(delay * 2, 30)

    raise RuntimeError(f"风格化失败，已重试 {max_retries} 次: {last_error}") from last_error


def _extract_image_from_response(resp) -> bytes | None:
    if not resp.candidates:
        return None
    for part in resp.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            return part.inline_data.data
    return None


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
