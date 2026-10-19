"""图片生成：按「设置 → 模型 → 图片生成」的配置调用。

两种接口：
- gemini：Gemini generateContent（responseModalities 含 IMAGE），参考图和提示词一起发送
- openai：OpenAI Images API，没有参考图走 /images/generations，有参考图走 /images/edits
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from src.providers import settings as provider_settings
from src.providers.http import (
    ProviderError,
    ProviderHTTPError,
    gemini_root,
    http_client,
    is_transient,
    openai_base,
    raise_for_status,
    read_image,
)
from src.providers.llm import gemini_model_path

logger = logging.getLogger(__name__)


@dataclass
class GeneratedImage:
    data: bytes
    mime_type: str
    text: str | None = None  # 模型附带的文字说明（如果有）


class NoImageError(ProviderError):
    """模型这次没有返回图片（常见于只回了文字），重试通常能好。"""

    def __init__(self, message: str):
        super().__init__(message, retryable=True)


def generate(
    prompt: str,
    reference_images: list[str | Path] | None = None,
    *,
    aspect_ratio: str | None = None,
    model: str | None = None,
    max_retries: int = 3,
    timeout: float = 300.0,
) -> GeneratedImage:
    """生成一张图片。

    Args:
        prompt: 提示词。
        reference_images: 参考图路径（编辑时第一张是待编辑的原图）。
        aspect_ratio: "9:16" / "16:9" 等，OpenAI Images 据此选择尺寸；Gemini 由提示词控制画幅。
        model: 临时覆盖配置里的模型名。
    """
    endpoint = provider_settings.resolve("image", model)
    refs = [Path(p) for p in reference_images or []]
    for ref in refs:
        if not ref.exists():
            raise FileNotFoundError(f"参考图片不存在: {ref}")

    with provider_settings.request_slot(endpoint):  # 到了服务商的并发上限时排队
        provider = endpoint.provider
        last_error: Exception | None = None
        delay = 2.0
        for attempt in range(1, max_retries + 1):
            key = provider_settings.pick_key(provider)
            try:
                if endpoint.format == "openai":
                    result = _openai_images(endpoint, key, prompt, refs, aspect_ratio, timeout)
                else:
                    result = _gemini_image(endpoint, key, prompt, refs, timeout)
                provider_settings.report_key(provider, key, ok=True)
                return result
            except Exception as exc:
                last_error = exc
                auth_error = isinstance(exc, ProviderHTTPError) and exc.is_auth_error
                if (is_transient(exc) and not isinstance(exc, NoImageError)) or auth_error:
                    provider_settings.report_key(provider, key, ok=False)
                if not (is_transient(exc) or (auth_error and len(provider.api_keys) > 1)) or attempt == max_retries:
                    break
                logger.warning(f"[{provider.name} · {endpoint.model}] 图片生成重试 {attempt}/{max_retries}: {exc}")
                time.sleep(delay)
                delay = min(delay * 2, 30)
    raise RuntimeError(f"[{provider.name} · {endpoint.model}] 图片生成失败: {last_error}") from last_error


def _gemini_image(endpoint, key: str, prompt: str, refs: list[Path], timeout: float) -> GeneratedImage:
    parts: list[dict] = []
    for ref in refs:
        data, mime = read_image(ref)
        parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}})
    parts.append({"text": prompt})
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }
    url = f"{gemini_root(endpoint.provider.base_url)}/v1beta/models/{gemini_model_path(endpoint.model)}:generateContent"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["x-goog-api-key"] = key
    with http_client(timeout) as client:
        resp = client.post(url, headers=headers, json=body)
    raise_for_status(resp)
    data = resp.json()

    block = (data.get("promptFeedback") or {}).get("blockReason")
    if block:
        raise ProviderError(f"Gemini 拒绝了这个请求（{block}）")
    texts: list[str] = []
    for candidate in (data.get("candidates") or [])[:1]:
        for part in (candidate.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            mime = (inline or {}).get("mimeType") or (inline or {}).get("mime_type") or ""
            if inline and mime.startswith("image/") and inline.get("data"):
                return GeneratedImage(base64.b64decode(inline["data"]), mime, "\n".join(texts) or None)
            if part.get("text") and not part.get("thought"):
                texts.append(part["text"])
    detail = f"：{' '.join(texts)[:300]}" if texts else ""
    raise NoImageError(f"模型没有返回图片{detail}")


def _openai_size(model: str, aspect_ratio: str | None) -> str | None:
    """按画幅选 OpenAI Images 支持的尺寸；不认识的模型在没有画幅要求时不传 size。"""
    name = model.lower()
    if "dall-e-2" in name:
        return "1024x1024"
    if "dall-e-3" in name:
        return {"9:16": "1024x1792", "16:9": "1792x1024"}.get(aspect_ratio or "", "1024x1024")
    sizes = {"9:16": "1024x1536", "16:9": "1536x1024", "1:1": "1024x1024"}
    if aspect_ratio in sizes:
        return sizes[aspect_ratio]
    return "auto" if name.startswith("gpt-image") else None


def _openai_images(endpoint, key: str, prompt: str, refs: list[Path], aspect_ratio: str | None, timeout: float) -> GeneratedImage:
    base = openai_base(endpoint.provider.base_url)
    size = endpoint.size or _openai_size(endpoint.model, aspect_ratio)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with http_client(timeout) as client:
        if refs:
            fields = {"model": endpoint.model, "prompt": prompt, "n": "1"}
            if size:
                fields["size"] = size
            field_name = "image[]" if len(refs) > 1 else "image"
            files = []
            for ref in refs:
                data, mime = read_image(ref)
                files.append((field_name, (ref.name, data, mime)))
            resp = client.post(f"{base}/images/edits", headers=headers, data=fields, files=files)
        else:
            body: dict = {"model": endpoint.model, "prompt": prompt, "n": 1}
            if size:
                body["size"] = size
            resp = client.post(f"{base}/images/generations", headers=headers, json=body)
        raise_for_status(resp)
        items = resp.json().get("data") or []
        item = items[0] if items else {}
        if item.get("b64_json"):
            return GeneratedImage(base64.b64decode(item["b64_json"]), "image/png", item.get("revised_prompt"))
        if item.get("url"):
            download = client.get(item["url"])
            raise_for_status(download)
            mime = download.headers.get("content-type", "image/png").split(";")[0]
            return GeneratedImage(download.content, mime, item.get("revised_prompt"))
    raise NoImageError("响应里没有 b64_json 或 url")


def save(result: GeneratedImage, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(result.data)
    return output_path
