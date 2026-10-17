"""文本 / 多模态结构化分析工具（使用「设置」中配置的对话模型 / 视觉模型）。

用法：
    from src.providers.http import image_part
    from src.tools.gemini_text import analyze_text, analyze_multimodal

    result = analyze_text(prompt="...", schema=MyModel)
    result = analyze_multimodal(contents=[image_part("a.png"), "描述这张图"], schema=MyModel)
"""

from typing import TypeVar

from pydantic import BaseModel

from src.providers import llm

T = TypeVar("T", bound=BaseModel)


def analyze_text(
    prompt: str,
    schema: type[T],
    model: str | None = None,
    system_instruction: str = "",
    max_retries: int = 3,
) -> T:
    """纯文本结构化分析（对话模型），返回 Pydantic 对象。"""
    return llm.generate_json(
        "chat", [prompt], schema, system=system_instruction, model=model, max_retries=max_retries,
    )


def analyze_multimodal(
    contents: list,
    schema: type[T],
    model: str | None = None,
    system_instruction: str = "",
    max_retries: int = 3,
) -> T:
    """多模态结构化分析（视觉模型，未配置时用对话模型），返回 Pydantic 对象。

    contents 里可以是字符串或 src.providers.http.image_part() 构造的图片。
    """
    return llm.generate_json(
        "vision", contents, schema, system=system_instruction, model=model, max_retries=max_retries,
    )
