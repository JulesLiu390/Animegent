"""Tool 3: 场景分析。

分析单张图片的场景信息（地点、氛围、时间段等）。
"""

import logging
from pathlib import Path

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP

from src.providers.http import image_part
from src.tools.gemini_text import analyze_multimodal

logger = logging.getLogger(__name__)


class SceneDescription(BaseModel):
    """场景描述。"""
    description: str
    location_type: str
    mood: str
    time_of_day: str
    key_elements: list[str]


def register(mcp: FastMCP) -> None:
    """注册场景分析工具。"""

    @mcp.tool()
    def analyze_scene(
        image_path: str,
    ) -> dict:
        """分析图片中的场景信息（忽略人物，只关注环境）。

        Args:
            image_path: 图片路径。

        Returns:
            场景描述，包含地点类型、氛围、时间段、关键元素。
        """
        img_path = Path(image_path)
        if not img_path.exists():
            return {"error": f"图片不存在: {image_path}"}

        contents: list = [
            image_part(img_path),
            "Analyze the SCENE/LOCATION in this photo. Ignore all people.\n"
            "Describe: the environment, location type, mood/atmosphere, time of day, "
            "and list key visual elements (furniture, decorations, architecture, nature, etc.).",
        ]

        try:
            result = analyze_multimodal(contents=contents, schema=SceneDescription)
            return {
                "description": result.description,
                "location_type": result.location_type,
                "mood": result.mood,
                "time_of_day": result.time_of_day,
                "key_elements": result.key_elements,
                "source_image": image_path,
            }
        except Exception as e:
            return {"error": str(e)}
