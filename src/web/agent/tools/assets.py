"""素材元数据：每个素材目录下的 assets.json（{文件名: {name, description, source_face?}}），以及用视觉模型给图片命名。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel

from src.providers import llm
from src.providers.http import image_part

logger = logging.getLogger(__name__)


def load_assets_json(directory: Path) -> dict:
    p = directory / "assets.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def write_assets_json(directory: Path, data: dict) -> None:
    (directory / "assets.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_asset_meta(file_path: Path, name: str, description: str, source_face: str | None = None) -> None:
    """把素材的 name / description 写入所在目录的 assets.json。"""
    data = load_assets_json(file_path.parent)
    entry: dict[str, str] = {"name": name, "description": description}
    if source_face:
        entry["source_face"] = source_face
    data[file_path.name] = entry
    write_assets_json(file_path.parent, data)


_DESCRIBE_PROMPT = (
    'Analyze this image and respond with a JSON object containing exactly two fields:\n'
    '1. "name": a short snake_case name for this asset (max 4 words), suitable as a filename. '
    'Focus on the most distinctive visual features: clothing color/type, hair, accessories, scene type.\n'
    '   Examples: yellow_jacket_boy, pink_dress_girl, sunset_beach_scene, dark_alley\n'
    '2. "description": a concise one-sentence description of what is in the image (in {language}).\n\n'
    'Output ONLY valid JSON, no markdown, no extra text.\n'
    'Example: {{"name": "yellow_jacket_boy", "description": "{example}"}}'
)


class _AssetDescription(BaseModel):
    name: str
    description: str = ""


def describe_image(image_path: Path, lang: str = "zh") -> dict:
    """用视觉模型生成图片的名称（snake_case）和一句话描述；失败时返回通用名称。"""
    prompt = _DESCRIBE_PROMPT.format(
        language="English" if lang == "en" else "Chinese",
        example="Young male in yellow jacket, short hair, arms crossed" if lang == "en" else "穿黄色夹克的年轻男性，短发，双手交叉",
    )
    try:
        data = llm.generate_json("vision", [image_part(image_path), prompt], _AssetDescription, max_retries=2, timeout=60)
        name = data.name.lower().replace(" ", "_").replace("-", "_")
        name = "".join(c for c in name if c.isalnum() or c == "_").strip("_")
        return {"name": name[:40] if name else "asset", "description": data.description}
    except Exception as e:
        logger.warning(f"VLM 描述失败: {e}")
    return {"name": "asset", "description": ""}


def find_stylized_dir(face_path: Path) -> Path:
    """从人脸路径（projects/{name}/output/faces/…）推断项目的 stylized 输出目录。"""
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
    return face_path.parent
