"""Agent 对话历史 <-> SQLite JSON 的转换。

历史条目本身就是 JSON（格式见 src/providers/llm.py），这里只负责：
- 写库前去掉内联的图片数据：图片只按路径保存，发请求时再读取
- 读库时兼容旧版（Gemini Content 序列化）数据：旧版图片只留下「[图片路径: …]」文本标记，恢复成图片 part
"""

from __future__ import annotations

import re
from typing import Any

# Pattern used by the agent to mark image file paths before image parts.
_IMAGE_PATH_RE = re.compile(r"^\[图片路径: (.+)\]$")


def history_entry_to_json(entry: dict[str, Any]) -> dict[str, Any]:
    """历史条目 → 入库的 JSON dict（去掉内联图片数据）。"""
    parts = [
        dict(p) for p in entry.get("parts") or []
        if not (p.get("type") == "image" and not p.get("path"))
    ]
    return {"role": entry.get("role") or "user", "parts": parts}


def history_entry_from_json(d: dict[str, Any]) -> dict[str, Any]:
    """入库的 JSON dict → 历史条目，兼容旧版格式。"""
    raw_parts: list[dict[str, Any]] = [p for p in d.get("parts") or [] if isinstance(p, dict) and p.get("type")]
    parts: list[dict[str, Any]] = []
    for i, part in enumerate(raw_parts):
        parts.append(dict(part))
        if part["type"] != "text":
            continue
        match = _IMAGE_PATH_RE.match(part.get("text", ""))
        following = raw_parts[i + 1] if i + 1 < len(raw_parts) else None
        if match and not (following and following.get("type") == "image"):
            parts.append({"type": "image", "path": match.group(1)})
    return {"role": "model" if d.get("role") == "model" else "user", "parts": parts}
