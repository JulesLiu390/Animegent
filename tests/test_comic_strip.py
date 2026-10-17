"""测试条漫生成：4个角色 + 1个场景 → 一页条漫（使用「设置」中配置的图片生成模型）。

流程：
    角色图 + 场景图 + 提示词 → 图片模型生成条漫

运行: uv run python tests/test_comic_strip.py
"""

import logging
from pathlib import Path

from src.providers import image as image_provider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("tests/test_comic_strip/output")

# 素材路径
CHARACTER_PATHS = [
    Path("output/stylized/person_0.png"),
    Path("output/stylized/person_1.png"),
    Path("output/stylized/person_2.png"),
    Path("output/stylized/person_3.png"),
]
SCENE_PATH = Path("output/scenes/stylized/scene_1.png")


def generate_comic():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("生成条漫...")
    prompt = (
        "Image 1: Character A\n"
        "Image 2: Character B\n"
        "Image 3: Character C\n"
        "Image 4: Character D\n"
        "Image 5: Scene\n\n"
        "Generate a vertical comic strip (条漫) with 4-6 panels.\n\n"
        "STRICT: The comic contains ONLY these 4 characters (A, B, C, D) shown above. "
        "Do NOT invent or add ANY other characters. "
        "Each character's appearance must match their reference image exactly.\n\n"
        "Scene: Chinese New Year family dinner at this home.\n"
        "- Manga/comic layout, black panel borders, 9:16 vertical\n"
        "- Dialogue bubbles in Chinese\n"
        "- Vary camera angles\n"
        "- Every character appears in at least 2 panels\n"
        "Output a single vertical comic strip image."
    )

    result = image_provider.generate(prompt, [*CHARACTER_PATHS, SCENE_PATH], aspect_ratio="9:16")
    if result.text:
        logger.info(f"模型文字回复: {result.text}")

    output_path = image_provider.save(result, OUTPUT_DIR / "comic_strip.png")
    logger.info(f"条漫已保存: {output_path}")


if __name__ == "__main__":
    generate_comic()
