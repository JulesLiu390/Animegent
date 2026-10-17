"""场景分析工具 - 去人、去重、选代表、动画化。

用法：
    from src.tools.scene_analyzer import analyze_scenes

    result = analyze_scenes(["img1.jpg", "img2.jpg"], output_dir="output/scenes")
"""

import logging
from pathlib import Path

from pydantic import BaseModel

from src.providers.http import image_part
from src.tools.gemini_image import edit_image
from src.tools.gemini_text import analyze_multimodal

logger = logging.getLogger(__name__)

# 去人 prompt
REMOVE_PEOPLE_PROMPT = (
    "Remove ALL people and human figures from this photo. "
    "Fill the removed areas with natural background that matches the surrounding environment. "
    "Keep the scene, architecture, furniture, decorations, and all non-human elements intact. "
    "The result should look like a clean, empty version of the same location."
)

# 场景动画化 prompt
SCENE_STYLIZE_PROMPT = (
    "Transform this photo into a high-quality anime/illustration style background art. "
    "Requirements:\n"
    "- Convert to clean anime background art style (like Kyoto Animation or Makoto Shinkai)\n"
    "- Keep the same composition, perspective, and spatial layout\n"
    "- Maintain all architectural details, furniture, and decorations\n"
    "- Use vibrant, warm anime-style coloring and lighting\n"
    "- Add subtle anime-style atmosphere (soft light rays, gentle color grading)\n"
    "- No people or human figures in the output\n"
    "- 16:9 landscape aspect ratio\n"
    "Output a single anime-style background image."
)


class SceneInfo(BaseModel):
    """单个场景信息。"""
    scene_id: int
    description: str
    mood: str
    time_of_day: str
    location_type: str
    best_image_index: int
    all_image_indices: list[int]
    reason: str


class SceneAnalysisResult(BaseModel):
    """场景分析结果。"""
    scenes: list[SceneInfo]


def _remove_people(
    image_path: Path,
    output_path: Path,
) -> Path:
    """用图片编辑模型去除图片中的人物。"""
    return edit_image(
        image_path=image_path,
        prompt=REMOVE_PEOPLE_PROMPT,
        output_path=output_path,
    )


def _analyze_and_deduplicate(image_paths: list[Path]) -> SceneAnalysisResult:
    """用视觉模型分析所有图片，去重并选出代表场景。"""
    contents: list = [image_part(img_path) for img_path in image_paths]

    index_desc = "\n".join(f"Image {i + 1}: {p.name}" for i, p in enumerate(image_paths))
    contents.append(
        f"You are given {len(image_paths)} photos:\n{index_desc}\n\n"
        "Analyze the SCENES/LOCATIONS in these photos (ignore all people).\n"
        "Group photos that show the SAME location/scene together.\n"
        "For each unique scene, pick the best representative image "
        "(best composition, lighting, most complete view of the location).\n\n"
        "Return 0-based image indices.\n"
        "Example: if images 0,2,5 are the same restaurant and image 2 is best "
        "→ scene with best_image_index=2, all_image_indices=[0,2,5]"
    )

    return analyze_multimodal(contents=contents, schema=SceneAnalysisResult)


def analyze_scenes(
    image_paths: list[str | Path],
    output_dir: str | Path,
) -> tuple[SceneAnalysisResult, list[Path]]:
    """完整场景分析流程：去重 → 去人 → 动画化。

    Args:
        image_paths: 输入图片路径列表。
        output_dir: 输出目录。

    Returns:
        (场景分析JSON结果, 动画化场景图片路径列表)
    """
    image_paths = [Path(p) for p in image_paths]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. LLM 分析去重，选出代表场景
    logger.info(f"分析 {len(image_paths)} 张图片的场景...")
    analysis = _analyze_and_deduplicate(image_paths)
    logger.info(f"识别出 {len(analysis.scenes)} 个独立场景")

    # 保存分析 JSON
    json_path = output_dir / "scenes.json"
    json_path.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
    logger.info(f"场景分析 JSON 已保存: {json_path}")

    # 2. 对每个代表场景：去人 → 动画化
    no_people_dir = output_dir / "no_people"
    no_people_dir.mkdir(parents=True, exist_ok=True)
    stylized_dir = output_dir / "stylized"
    stylized_dir.mkdir(parents=True, exist_ok=True)

    stylized_paths: list[Path] = []
    for scene in analysis.scenes:
        best_img = image_paths[scene.best_image_index]
        logger.info(
            f"场景 {scene.scene_id} ({scene.description}): "
            f"代表图 {best_img.name}"
        )

        # 去人
        no_people_path = no_people_dir / f"scene_{scene.scene_id}.png"
        try:
            _remove_people(best_img, no_people_path)
            logger.info(f"  去人完成: {no_people_path}")
        except Exception as e:
            logger.error(f"  去人失败: {e}，使用原图继续")
            no_people_path = best_img

        # 动画化
        stylized_path = stylized_dir / f"scene_{scene.scene_id}.png"
        try:
            edit_image(
                image_path=no_people_path,
                prompt=SCENE_STYLIZE_PROMPT,
                output_path=stylized_path,
                aspect_ratio="16:9",
            )
            logger.info(f"  动画化完成: {stylized_path}")
            stylized_paths.append(stylized_path)
        except Exception as e:
            logger.error(f"  动画化失败: {e}")

    return analysis, stylized_paths
