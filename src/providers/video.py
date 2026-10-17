"""视频生成：按「设置 → 模型 → 视频生成」的配置调用。

三种接口：
- unified：聚合站常见的统一视频接口（POST /v1/video/create + GET /v1/video/query，云雾、New API 等）
- openai：OpenAI Sora（POST /v1/videos，轮询后下载 /v1/videos/{id}/content）
- gemini：Google Veo（Gemini API 的 generate_videos 长任务）
"""

from __future__ import annotations

import base64
import io
import logging
import time
import uuid
from pathlib import Path

import httpx

from src.providers import settings as provider_settings
from src.providers.http import (
    ProviderError,
    api_root,
    gemini_root,
    guess_mime,
    http_client,
    is_transient,
    openai_base,
    raise_for_status,
)

logger = logging.getLogger(__name__)

_MAX_UNIFIED_IMAGES = 3


def generate_video(
    prompt: str,
    images: list[str] | None = None,
    *,
    output_dir: str | Path,
    aspect_ratio: str = "16:9",
    model: str | None = None,
    poll_interval: int = 3,
    timeout: int = 600,
) -> Path:
    """生成视频并下载到 output_dir，返回视频文件路径。

    Args:
        prompt: 视频提示词。
        images: 参考图/首帧（本地路径或 URL）。
        aspect_ratio: "16:9" 或 "9:16"。
        model: 临时覆盖配置里的模型名。
    """
    endpoint = provider_settings.resolve("video", model)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    images = images or []
    for img in images:
        if not img.startswith(("http://", "https://")) and not Path(img).exists():
            raise FileNotFoundError(f"图片不存在: {img}")

    key = provider_settings.pick_key(endpoint.provider)
    try:
        if endpoint.format == "openai":
            path = _sora(endpoint, key, prompt, images, aspect_ratio, out, poll_interval, timeout)
        elif endpoint.format == "gemini":
            path = _veo(endpoint, key, prompt, images, aspect_ratio, out, poll_interval, timeout)
        else:
            path = _unified(endpoint, key, prompt, images, aspect_ratio, out, poll_interval, timeout)
    except Exception as exc:
        if is_transient(exc):
            provider_settings.report_key(endpoint.provider, key, ok=False)
        exc.args = (f"[{endpoint.provider.name} · {endpoint.model}] {exc}",)
        raise
    provider_settings.report_key(endpoint.provider, key, ok=True)
    logger.info(f"视频已保存: {path}")
    return path


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"} if key else {}


def _deadline_loop(timeout: int, poll_interval: int):
    """轮询计时：每次产出已等待的秒数，超时抛 TimeoutError。"""
    start = time.monotonic()
    while True:
        elapsed = time.monotonic() - start
        if elapsed > timeout:
            raise TimeoutError(f"视频生成超时（{timeout}s）")
        yield elapsed
        time.sleep(poll_interval)


# ========== 统一视频接口（/v1/video/create） ==========

def _unified(endpoint, key, prompt, images, aspect_ratio, out: Path, poll_interval: int, timeout: int) -> Path:
    if len(images) > _MAX_UNIFIED_IMAGES:
        raise ValueError(f"最多支持 {_MAX_UNIFIED_IMAGES} 张参考图片，收到: {len(images)}")
    root = api_root(endpoint.provider.base_url)
    model = endpoint.model
    body: dict = {"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio}
    if model.startswith("grok"):
        body["size"] = "720P"
    elif model.startswith("veo"):
        body.update(enhance_prompt=True, person_generation="allow_adult")
    if images:
        body["images"] = [_image_ref(img) for img in images]
    headers = {**_auth(key), "Content-Type": "application/json", "Accept": "application/json"}

    with http_client(300, connect=30) as client:
        resp = client.post(f"{root}/v1/video/create", headers=headers, json=body)
        raise_for_status(resp)
        task_id = resp.json().get("id")
        if not task_id:
            raise ProviderError(f"提交任务失败，没有返回任务 id: {resp.text[:500]}")
        logger.info(f"视频任务已提交: {task_id} (model={model})")

        for elapsed in _deadline_loop(timeout, poll_interval):
            try:
                poll = client.get(f"{root}/v1/video/query", params={"id": task_id}, headers=headers, timeout=30)
                raise_for_status(poll)
                data = poll.json()
            except (httpx.TransportError, ValueError) as exc:
                logger.warning(f"轮询失败，稍后重试: {exc}")
                continue
            status = data.get("status", "")
            logger.debug(f"[{elapsed:.0f}s] {status} (progress={data.get('progress', '?')})")
            if status == "completed":
                video_url = data.get("video_url")
                if not video_url:
                    raise ProviderError(f"任务完成但没有 video_url: {data}")
                return _download(client, video_url, out / _safe_name(task_id), {})
            if status in ("failed", "error"):
                raise ProviderError(f"视频生成失败: {data}")
    raise AssertionError("unreachable")


def _image_ref(img: str) -> str:
    """URL 原样保留，本地文件转为 base64 data URI。"""
    if img.startswith(("http://", "https://")):
        return img
    return f"data:{guess_mime(img)};base64,{base64.b64encode(Path(img).read_bytes()).decode()}"


# ========== OpenAI Sora（/v1/videos） ==========

def _sora(endpoint, key, prompt, images, aspect_ratio, out: Path, poll_interval: int, timeout: int) -> Path:
    base = openai_base(endpoint.provider.base_url)
    size = "720x1280" if aspect_ratio == "9:16" else "1280x720"
    fields = {"model": endpoint.model, "prompt": prompt, "size": size}
    files = None
    if images:
        # Sora 要求参考图和视频尺寸完全一致
        files = {"input_reference": ("first_frame.png", _fit_image(images[0], size), "image/png")}

    with http_client(300, connect=30) as client:
        resp = client.post(f"{base}/videos", headers=_auth(key), data=fields, files=files)
        raise_for_status(resp)
        video_id = resp.json().get("id")
        if not video_id:
            raise ProviderError(f"提交任务失败，没有返回 id: {resp.text[:500]}")
        logger.info(f"Sora 任务已提交: {video_id}")

        for _ in _deadline_loop(timeout, poll_interval):
            try:
                poll = client.get(f"{base}/videos/{video_id}", headers=_auth(key), timeout=30)
                raise_for_status(poll)
                data = poll.json()
            except (httpx.TransportError, ValueError) as exc:
                logger.warning(f"轮询失败，稍后重试: {exc}")
                continue
            status = data.get("status", "")
            if status == "completed":
                return _download(client, f"{base}/videos/{video_id}/content", out / _safe_name(video_id), _auth(key))
            if status == "failed":
                error = data.get("error") or {}
                raise ProviderError(f"视频生成失败: {error.get('message') if isinstance(error, dict) else error or data}")
    raise AssertionError("unreachable")


def _fit_image(path: str, size: str) -> bytes:
    """把图片居中裁剪缩放到指定尺寸，返回 PNG bytes。"""
    from PIL import Image, ImageOps

    width, height = (int(v) for v in size.split("x"))
    if path.startswith(("http://", "https://")):
        with http_client(60) as client:
            resp = client.get(path)
            raise_for_status(resp)
            source = io.BytesIO(resp.content)
    else:
        source = path
    img = ImageOps.fit(Image.open(source).convert("RGB"), (width, height))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ========== Google Veo（Gemini API） ==========

def _veo(endpoint, key, prompt, images, aspect_ratio, out: Path, poll_interval: int, timeout: int) -> Path:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=key or None,
        http_options=types.HttpOptions(base_url=gemini_root(endpoint.provider.base_url), timeout=120_000),
    )
    kwargs: dict = {
        "model": endpoint.model,
        "prompt": prompt,
        "config": types.GenerateVideosConfig(aspect_ratio=aspect_ratio),
    }
    if images:
        first = images[0]
        if first.startswith(("http://", "https://")):
            raise ValueError("Veo 的首帧需要是本地图片")
        kwargs["image"] = types.Image(image_bytes=Path(first).read_bytes(), mime_type=guess_mime(first))

    operation = client.models.generate_videos(**kwargs)
    logger.info(f"Veo 任务已提交: {operation.name}")
    for _ in _deadline_loop(timeout, poll_interval):
        if operation.done:
            break
        operation = client.operations.get(operation)
    if operation.error:
        raise ProviderError(f"视频生成失败: {operation.error}")
    response = operation.response or operation.result
    videos = response.generated_videos if response else None
    if not videos or not videos[0].video:
        reasons = getattr(response, "rai_media_filtered_reasons", None) if response else None
        raise ProviderError(f"Veo 没有返回视频{f'（{reasons}）' if reasons else ''}")
    data = client.files.download(file=videos[0].video)
    path = out / f"veo_{uuid.uuid4().hex[:8]}.mp4"
    path.write_bytes(data)
    return path


# ========== 下载 ==========

def _safe_name(task_id: str) -> str:
    return task_id.replace(":", "_").replace("/", "_")


def _download(client: httpx.Client, url: str, stem: Path, headers: dict) -> Path:
    resp = client.get(url, headers=headers, timeout=180)
    raise_for_status(resp)
    ext = ".webm" if "webm" in resp.headers.get("content-type", "") else ".mp4"
    path = stem.with_name(stem.name + ext)
    path.write_bytes(resp.content)
    return path
