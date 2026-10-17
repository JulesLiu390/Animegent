"""图片生成 / 编辑工具（使用「设置」中配置的图片生成模型）。

用法：
    from src.tools.gemini_image import generate_image

    path = generate_image(prompt="一只可爱的猫咪", output_path="output/cat.jpg")
"""

import logging
from pathlib import Path

from src.providers import image as image_provider

logger = logging.getLogger(__name__)


def generate_image(
    prompt: str,
    output_path: str | Path,
    reference_images: list[str | Path] | None = None,
    model: str | None = None,
    aspect_ratio: str | None = None,
    max_retries: int = 3,
) -> Path:
    """生成图片。

    Args:
        prompt: 图片描述提示词。
        output_path: 输出图片路径。
        reference_images: 参考图片路径列表（可选），会和 prompt 一起发送。
        model: 临时覆盖配置里的图片模型（可选）。
        aspect_ratio: 期望画幅，如 "9:16"、"16:9"（可选）。
        max_retries: 最大尝试次数。

    Returns:
        生成的图片路径。
    """
    result = image_provider.generate(
        prompt, reference_images, aspect_ratio=aspect_ratio, model=model, max_retries=max_retries,
    )
    path = image_provider.save(result, output_path)
    logger.info(f"图片已保存: {path}")
    return path


def edit_image(
    image_path: str | Path,
    prompt: str,
    output_path: str | Path | None = None,
    reference_images: list[str | Path] | None = None,
    model: str | None = None,
    aspect_ratio: str | None = None,
    max_retries: int = 3,
) -> Path:
    """编辑已有图片。

    Args:
        image_path: 待编辑的图片路径。
        prompt: 编辑指令。
        output_path: 输出路径，默认在原图旁生成 _edited 后缀文件。
        reference_images: 参考图片路径列表（可选）。
        model: 临时覆盖配置里的图片模型（可选）。
        aspect_ratio: 期望画幅（可选，默认沿用原图）。
        max_retries: 最大尝试次数。

    Returns:
        编辑后的图片路径。
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片不存在: {image_path}")
    if output_path is None:
        output_path = image_path.parent / f"{image_path.stem}_edited{image_path.suffix}"

    result = image_provider.generate(
        prompt, [image_path, *(reference_images or [])],
        aspect_ratio=aspect_ratio, model=model, max_retries=max_retries,
    )
    path = image_provider.save(result, output_path)
    logger.info(f"编辑后图片已保存: {path}")
    return path
