"""服务商调用的公共工具：错误类型、Base URL 规范化、SSE 解析、图片读取。"""

from __future__ import annotations

import base64
import io
import json
import re
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import httpx

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_GEMINI_ROOT = "https://generativelanguage.googleapis.com"
DEFAULT_ANTHROPIC_BASE = "https://api.anthropic.com/v1"


# ========== 错误 ==========

class ProviderError(RuntimeError):
    """服务商返回了错误，或返回的内容无法使用。"""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class ProviderHTTPError(ProviderError):
    """服务商返回了非 2xx 状态码。"""

    def __init__(self, status: int, body: str, url: str):
        self.status = status
        self.body = body
        self.url = url
        retryable = status in (408, 409, 425, 429) or status >= 500
        super().__init__(f"HTTP {status}（{url}）: {_summarize_body(body)}", retryable=retryable)

    @property
    def is_auth_error(self) -> bool:
        return self.status in (401, 403)


def _summarize_body(body: str) -> str:
    """从错误响应里提取可读的错误信息。"""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return (body or "").strip()[:500] or "(空响应)"
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        err = data.get("error", data)
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:500]
        if isinstance(err, str):
            return err[:500]
    return body.strip()[:500]


def is_transient(exc: BaseException) -> bool:
    """网络错误、限流、5xx 等换个 Key / 稍后重试可能成功的错误。"""
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, ProviderError) and exc.retryable


def raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        resp.read()
        body = resp.text
    except Exception:
        body = ""
    raise ProviderHTTPError(resp.status_code, body, str(resp.request.url))


def http_client(timeout: float, connect: float = 20.0) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout, connect=connect), follow_redirects=True)


# ========== Base URL 规范化 ==========
# 用户可能填域名、带 /v1、甚至整条接口地址，这里统一成各接口需要的形式。

_VERSION_SUFFIX = re.compile(r"/v\d+(?:beta|alpha)?\d*(?:/openai)?$")


def _clean(url: str | None) -> str:
    return (url or "").strip().rstrip("/")


def _strip_suffix(url: str, suffixes: tuple[str, ...]) -> str:
    for suffix in suffixes:
        if url.endswith(suffix):
            return url[: -len(suffix)].rstrip("/")
    return url


def _has_path(url: str) -> bool:
    return urlparse(url).path not in ("", "/")


def openai_base(url: str | None) -> str:
    """OpenAI 兼容接口的 base（含 /v1 等版本段）。只填了域名时补 /v1。"""
    url = _clean(url) or DEFAULT_OPENAI_BASE
    url = _strip_suffix(url, ("/chat/completions", "/images/generations", "/images/edits", "/models", "/videos"))
    return url if _has_path(url) else url + "/v1"


def gemini_root(url: str | None) -> str:
    """Gemini 原生接口的根地址（不含 /v1beta）。"""
    url = _strip_suffix(_clean(url) or DEFAULT_GEMINI_ROOT, ("/models",))
    return _VERSION_SUFFIX.sub("", url)


def anthropic_base(url: str | None) -> str:
    """Anthropic Messages API 的 base（含 /v1）。"""
    url = _strip_suffix(_clean(url) or DEFAULT_ANTHROPIC_BASE, ("/messages", "/models"))
    return url if _has_path(url) else url + "/v1"


def api_root(url: str | None) -> str:
    """去掉末尾版本段（/v1 等）后的根地址，用于路径里自带 /v1/... 的接口。"""
    return _VERSION_SUFFIX.sub("", _clean(url))


# ========== 流式响应 ==========

def iter_payloads(resp: httpx.Response) -> Iterator[str]:
    """逐个返回流式响应里的 JSON 字符串。

    正常情况是 SSE（三家接口都是一行 data 一个 JSON）；部分中转站即使请求了流式也直接返回完整 JSON
    （单个对象或数组），这种情况把整个响应拆成和流式一样的 JSON 片段返回。
    """
    lines = resp.iter_lines()
    first = next((line for line in lines if line.strip()), None)
    if first is None:
        return
    if first.startswith(("data:", "event:", "id:", ":")):
        for line in _chain(first, lines):
            if line.startswith("data:"):
                data = line[5:].strip()
                if data:
                    yield data
        return
    body = json.loads("\n".join(_chain(first, lines)))
    for item in body if isinstance(body, list) else [body]:
        yield json.dumps(item, ensure_ascii=False)


def _chain(first: str, rest: Iterator[str]) -> Iterator[str]:
    yield first
    yield from rest


def parse_json_text(text: str):
    """解析模型输出的 JSON，容忍 ```json 代码块和前后多余的文字。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
        end = max(t.rfind("}"), t.rfind("]"))
        if starts and end > min(starts):
            return json.loads(t[min(starts): end + 1])
        raise


# ========== 图片 ==========

# 主流多模态模型都支持的图片格式；其他格式（如 BMP）发送前转成 PNG
_COMMON_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
# 发给 LLM 的单张图片上限（Anthropic 单图限制 5MB，留出余量）
_MAX_LLM_IMAGE_BYTES = 3_500_000
_MAX_LLM_IMAGE_SIDE = 2048


def guess_mime(path: str | Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(Path(path).suffix.lower(), "application/octet-stream")


def image_part(source: str | Path | bytes, mime_type: str | None = None) -> dict:
    """构造消息里的图片 part：传路径按路径引用（发送时再读取），传 bytes 则内联。"""
    if isinstance(source, (bytes, bytearray)):
        return {"type": "image", "data": base64.b64encode(source).decode(), "mime_type": mime_type or "image/png"}
    return {"type": "image", "path": str(source)}


def read_image(path: str | Path) -> tuple[bytes, str]:
    """读取图片文件，返回 (bytes, mime)。常见格式原样返回，其他格式转成 PNG。"""
    path = Path(path)
    data = path.read_bytes()
    mime = guess_mime(path)
    if mime in _COMMON_IMAGE_MIMES:
        return data, mime
    return _reencode(data, max_side=None)


def load_llm_image(part: dict) -> tuple[str, str] | None:
    """读取消息里的图片 part，返回 (base64, mime)；文件已不存在时返回 None。

    超过大小限制的图片会被缩小重新编码，避免超出各家单图大小限制。
    """
    if part.get("data"):
        return part["data"], part.get("mime_type") or "image/png"
    path = Path(part.get("path") or "")
    if not path.is_file():
        return None
    stat = path.stat()
    mime = guess_mime(path)
    if mime in _COMMON_IMAGE_MIMES and stat.st_size <= _MAX_LLM_IMAGE_BYTES:
        return base64.b64encode(path.read_bytes()).decode(), mime
    data, mime = _shrunk_image(str(path), stat.st_mtime_ns, stat.st_size)
    return base64.b64encode(data).decode(), mime


@lru_cache(maxsize=16)
def _shrunk_image(path: str, mtime_ns: int, size: int) -> tuple[bytes, str]:
    # mtime/size 只参与缓存键：文件变化后会重新编码
    return _reencode(Path(path).read_bytes(), max_side=_MAX_LLM_IMAGE_SIDE if size > _MAX_LLM_IMAGE_BYTES else None)


def _reencode(data: bytes, max_side: int | None) -> tuple[bytes, str]:
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    if max_side:
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img.convert("RGBA").save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "image/png"
    img.convert("RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"
