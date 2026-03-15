"""视频生成工具 - 通过 yunwu.ai 中转站调用。

支持模型：
- Grok Video 3（默认，10 秒）
- VEO 3.1（standard / fast / 4k）

用法：
    from src.tools.video_generator import generate_video

    output_dir = generate_video(prompt="...", images=["ref.jpg"])
"""

import base64
import logging
import time
from pathlib import Path

import httpx

from src.tools.models.registry import get_api_key, get_api_base, mark_key_failure, mark_key_success

logger = logging.getLogger(__name__)

# 模型映射
_MODEL_MAP = {
    "grok": "grok-video-3",
    "standard": "veo3.1",
    "fast": "veo3.1-fast-components",
    "4k": "veo3.1-4k",
}

_GROK_PREFIX = "grok-"

DEFAULT_OUTPUT_DIR = Path("output/videos")


def generate_video(
    prompt: str,
    images: list[str] | None = None,
    aspect_ratio: str = "16:9",
    mode: str = "grok",
    enhance_prompt: bool = True,
    output_dir: str | Path | None = None,
    poll_interval: int = 3,
    timeout: int = 600,
    person_generation: str = "allow_adult",
) -> Path:
    """生成视频并下载到本地文件夹。

    Args:
        prompt: 视频描述提示词。
        images: 参考图片列表（URL 或本地路径），最多 3 张。
        aspect_ratio: 宽高比，"16:9"（横屏）或 "9:16"（竖屏）。
        mode: "grok"（默认）、"standard"、"fast"、"4k"。
        enhance_prompt: 是否自动增强提示词（仅 VEO）。
        output_dir: 输出文件夹路径，默认 output/videos。
        poll_interval: 轮询间隔（秒），默认 3。
        timeout: 最大等待时间（秒），默认 600。
        person_generation: 人物生成策略（仅 VEO）。

    Returns:
        输出文件夹的 Path 对象。
    """
    if mode not in _MODEL_MAP:
        raise ValueError(f"mode 必须是 {list(_MODEL_MAP.keys())}，收到: {mode}")

    if images and len(images) > 3:
        raise ValueError(f"最多支持 3 张参考图片，收到: {len(images)}")

    model = _MODEL_MAP[mode]
    out = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    # 1. 提交任务
    task_id = _submit_task(model, prompt, images, aspect_ratio, enhance_prompt, person_generation)
    logger.info(f"任务已提交: {task_id}")

    # 2. 轮询等待完成
    video_url = _poll_task(task_id, poll_interval, timeout)

    # 3. 下载视频
    video_path = _download_video(video_url, task_id, out)
    logger.info(f"视频已保存: {video_path}")

    return video_path


def _submit_task(
    model: str,
    prompt: str,
    images: list[str] | None,
    aspect_ratio: str,
    enhance_prompt: bool,
    person_generation: str = "allow_adult",
) -> str:
    """通过 POST /v1/video/create 提交任务。"""
    is_grok = model.startswith(_GROK_PREFIX)

    if is_grok:
        body: dict = {
            "model": model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "size": "720P",
        }
    else:
        body = {
            "model": model,
            "prompt": prompt,
            "enhance_prompt": enhance_prompt,
            "aspect_ratio": aspect_ratio,
            "person_generation": person_generation,
        }

    if images:
        body["images"] = _prepare_images(images)

    key = get_api_key()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        with httpx.Client(timeout=httpx.Timeout(300, connect=30)) as client:
            resp = client.post(f"{get_api_base()}/v1/video/create", headers=headers, json=body)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError,
            ConnectionError, TimeoutError, OSError):
        mark_key_failure(key)
        raise

    if resp.status_code != 200:
        try:
            err = resp.json()
        except Exception:
            err = resp.text
        raise RuntimeError(f"提交任务失败 (HTTP {resp.status_code}): {err}")

    mark_key_success(key)
    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f"提交任务响应非 JSON: {resp.text[:500]}")
    task_id = data.get("id")
    if not task_id:
        raise RuntimeError(f"提交任务失败，无 task_id: {data}")

    logger.info(f"模型: {model} | 宽高比: {aspect_ratio}")
    return task_id


def _prepare_images(images: list[str]) -> list[str]:
    """准备图片列表。URL 原样保留，本地文件转为 base64 data URI。"""
    result = []
    for img in images:
        if img.startswith(("http://", "https://")):
            result.append(img)
        else:
            p = Path(img)
            if not p.exists():
                raise FileNotFoundError(f"图片不存在: {p}")
            mime = _guess_mime(p)
            b64 = base64.b64encode(p.read_bytes()).decode()
            result.append(f"data:{mime};base64,{b64}")
    return result


def _poll_task(task_id: str, interval: int, timeout: int) -> str:
    """轮询 GET /v1/video/query?id=xxx，返回 video_url。"""
    elapsed = 0
    with httpx.Client(timeout=30) as client:
        while elapsed < timeout:
            key = get_api_key()
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            try:
                resp = client.get(
                    f"{get_api_base()}/v1/video/query",
                    params={"id": task_id},
                    headers=headers,
                )
                resp.raise_for_status()
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError,
                    ConnectionError, TimeoutError, OSError) as e:
                mark_key_failure(key)
                logger.warning(f"轮询网络错误，切换 key 重试: {e}")
                time.sleep(interval)
                elapsed += interval
                continue

            try:
                data = resp.json()
            except Exception:
                logger.warning(f"轮询响应非 JSON，跳过: {resp.text[:200]}")
                time.sleep(interval)
                elapsed += interval
                continue

            status = data.get("status", "")
            progress = data.get("progress", "?")
            logger.debug(f"[{elapsed}s] {status} (progress={progress})")

            if status == "completed":
                video_url = data.get("video_url")
                if not video_url:
                    raise RuntimeError(f"任务完成但无 video_url: {data}")
                return video_url
            elif status in ("failed", "error"):
                raise RuntimeError(f"视频生成失败: {data}")

            time.sleep(interval)
            elapsed += interval

    raise TimeoutError(f"视频生成超时（{timeout}s）")


def _download_video(video_url: str, task_id: str, output_dir: Path) -> Path:
    """从 video_url 下载视频文件。"""
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        resp = client.get(video_url)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        ext = ".mp4"
        if "webm" in content_type:
            ext = ".webm"

        filename = f"{task_id.replace(':', '_').replace('/', '_')}{ext}"
        filepath = output_dir / filename
        filepath.write_bytes(resp.content)
        return filepath


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
