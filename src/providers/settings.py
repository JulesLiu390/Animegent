"""API 服务商与模型分配配置。

配置保存在项目根目录的 settings.json（已 gitignore，不会通过 /files 暴露），在前端「设置」界面里编辑：
- providers: API 服务商（API 格式、Base URL、一个或多个 Key、可选模型列表）
- models: 每种用途用哪个服务商的哪个模型
    chat   对话 Agent（需要支持工具调用）
    vision 素材命名/描述、场景分析等看图任务（未配置时用 chat）
    image  图片生成，format: gemini / openai
    video  视频生成，format: unified / openai / gemini

settings.json 不存在时，会把旧版 .env 里的 API_KEYS / BASE_URL 导入成一个服务商，保持原有行为。
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "settings.json"
ENV_PATH = PROJECT_ROOT / ".env"

ApiFormat = Literal["openai_compatible", "gemini_official", "anthropic_native"]
ROLES = ("chat", "vision", "image", "video")
ROLE_FORMATS = {
    "image": ("gemini", "openai"),
    "video": ("unified", "openai", "gemini"),
}
ROLE_LABELS = {"chat": "对话模型", "vision": "视觉模型", "image": "图片生成模型", "video": "视频生成模型"}

# 旧版 .env 配置下代码里写死的模型
_LEGACY_MODELS = [
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",
    "gemini-3.1-flash-image-preview",
    "grok-video-3",
    "veo3.1",
    "veo3.1-fast-components",
    "veo3.1-4k",
]


class Provider(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    api_format: ApiFormat = "openai_compatible"
    base_url: str = ""
    api_keys: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)


class ModelAssignment(BaseModel):
    provider_id: str = ""
    model: str = ""
    format: str = ""  # 仅 image / video：调用哪种接口，留空按服务商推断
    size: str = ""  # 仅 OpenAI Images：留空按画幅自动选择


class ModelSettings(BaseModel):
    chat: ModelAssignment = Field(default_factory=ModelAssignment)
    vision: ModelAssignment = Field(default_factory=ModelAssignment)
    image: ModelAssignment = Field(default_factory=ModelAssignment)
    video: ModelAssignment = Field(default_factory=ModelAssignment)


class Settings(BaseModel):
    providers: list[Provider] = Field(default_factory=list)
    models: ModelSettings = Field(default_factory=ModelSettings)

    def provider(self, provider_id: str) -> Provider | None:
        return next((p for p in self.providers if p.id == provider_id), None)


class NotConfiguredError(RuntimeError):
    """某个用途还没有配置服务商或模型。"""


# ========== 读写 ==========

_lock = threading.RLock()
_cache: Settings | None = None
_cache_mtime: float | None = None


def load() -> Settings:
    """读取配置（返回副本，修改后需调用 save）。"""
    global _cache, _cache_mtime
    with _lock:
        if not SETTINGS_PATH.exists():
            return _bootstrap_from_env().model_copy(deep=True)
        mtime = SETTINGS_PATH.stat().st_mtime
        if _cache is None or mtime != _cache_mtime:
            _cache = Settings.model_validate_json(SETTINGS_PATH.read_text(encoding="utf-8"))
            _cache_mtime = mtime
        return _cache.model_copy(deep=True)


def save(settings: Settings) -> None:
    global _cache, _cache_mtime
    with _lock:
        tmp = SETTINGS_PATH.with_name(SETTINGS_PATH.name + ".tmp")
        tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)  # 文件里有 API Key
        os.replace(tmp, SETTINGS_PATH)
        _cache = settings.model_copy(deep=True)
        _cache_mtime = SETTINGS_PATH.stat().st_mtime


def _bootstrap_from_env() -> Settings:
    """settings.json 不存在：导入旧版 .env 的 API_KEYS / BASE_URL；都没有就返回空配置。"""
    from dotenv import dotenv_values

    env = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    raw_keys = os.environ.get("API_KEYS") or env.get("API_KEYS") or ""
    keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
    if not keys:
        return Settings()

    base_url = os.environ.get("BASE_URL") or env.get("BASE_URL") or "https://yunwu.ai/v1"
    host = urlparse(base_url).hostname or base_url
    provider = Provider(
        name=f"{host}（从 .env 导入）",
        api_format="gemini_official",
        base_url=base_url,
        api_keys=keys,
        models=list(_LEGACY_MODELS),
    )
    settings = Settings(
        providers=[provider],
        models=ModelSettings(
            chat=ModelAssignment(provider_id=provider.id, model="gemini-3-flash-preview"),
            vision=ModelAssignment(provider_id=provider.id, model="gemini-2.5-flash-lite"),
            image=ModelAssignment(provider_id=provider.id, model="gemini-3.1-flash-image-preview", format="gemini"),
            video=ModelAssignment(provider_id=provider.id, model="grok-video-3", format="unified"),
        ),
    )
    save(settings)
    return settings


# ========== 增删改（供设置界面使用）==========

def create_provider(data: dict) -> Provider:
    with _lock:
        settings = load()
        provider = Provider(**{k: v for k, v in data.items() if k != "id" and v is not None})
        provider.api_keys = _clean_keys(provider.api_keys)
        settings.providers.append(provider)
        save(settings)
        return provider


def update_provider(provider_id: str, data: dict) -> Provider:
    """更新服务商；data 里 api_keys 为 None 时保留原来的 Key。"""
    with _lock:
        settings = load()
        provider = settings.provider(provider_id)
        if provider is None:
            raise KeyError(provider_id)
        merged = provider.model_dump()
        merged.update({k: v for k, v in data.items() if v is not None and k != "id"})
        merged["api_keys"] = _clean_keys(merged["api_keys"])
        updated = Provider(**merged)
        settings.providers = [updated if p.id == provider_id else p for p in settings.providers]
        save(settings)
        return updated


def delete_provider(provider_id: str) -> bool:
    with _lock:
        settings = load()
        before = len(settings.providers)
        settings.providers = [p for p in settings.providers if p.id != provider_id]
        if len(settings.providers) == before:
            return False
        for role in ROLES:
            if getattr(settings.models, role).provider_id == provider_id:
                setattr(settings.models, role, ModelAssignment())
        save(settings)
        return True


def update_models(data: dict) -> ModelSettings:
    """更新模型分配，data: {role: {provider_id, model, format, size}}，未出现的用途保持不变。"""
    with _lock:
        settings = load()
        for role, value in data.items():
            if role not in ROLES or value is None:
                continue
            assignment = ModelAssignment(**value)
            assignment.model = assignment.model.strip()
            if assignment.provider_id and settings.provider(assignment.provider_id) is None:
                raise ValueError(f"服务商不存在: {assignment.provider_id}")
            allowed = ROLE_FORMATS.get(role)
            if allowed is None:
                assignment.format = ""
            elif assignment.format and assignment.format not in allowed:
                raise ValueError(f"{ROLE_LABELS[role]}不支持接口类型 {assignment.format}")
            setattr(settings.models, role, assignment)
        save(settings)
        return settings.models


def _clean_keys(keys: list[str]) -> list[str]:
    seen: list[str] = []
    for key in keys:
        key = key.strip()
        if key and key not in seen:
            seen.append(key)
    return seen


def mask_key(key: str) -> str:
    if len(key) <= 10:
        return "****"
    return f"{key[:6]}…{key[-4:]}"


def public_dict(settings: Settings | None = None) -> dict:
    """给前端的配置视图：API Key 只给数量和脱敏预览。"""
    settings = settings or load()
    providers = []
    for p in settings.providers:
        item = p.model_dump(exclude={"api_keys"})
        item["key_count"] = len(p.api_keys)
        item["key_previews"] = [mask_key(k) for k in p.api_keys]
        providers.append(item)
    return {"providers": providers, "models": settings.models.model_dump()}


# ========== 解析某个用途的配置 ==========

@dataclass
class Endpoint:
    role: str
    provider: Provider
    model: str
    format: str  # chat/vision: 服务商的 api_format；image/video: 接口类型
    size: str = ""


def resolve(role: str, model: str | None = None) -> Endpoint:
    """取某个用途当前配置的服务商和模型；model 可临时覆盖模型名。"""
    settings = load()
    assignment: ModelAssignment = getattr(settings.models, role)
    if role == "vision" and not (assignment.provider_id and assignment.model):
        assignment = settings.models.chat
    provider = settings.provider(assignment.provider_id) if assignment.provider_id else None
    model_name = (model or assignment.model).strip()
    if provider is None or not model_name:
        raise NotConfiguredError(f"尚未配置{ROLE_LABELS[role]}，请点击右上角「⚙ 设置」选择服务商和模型")
    if role in ROLE_FORMATS:
        fmt = assignment.format or default_format(role, provider)
    else:
        fmt = provider.api_format
    return Endpoint(role=role, provider=provider, model=model_name, format=fmt, size=assignment.size.strip())


def default_format(role: str, provider: Provider) -> str:
    """image / video 没有指定接口类型时，按服务商推断。"""
    base = provider.base_url.lower()
    if role == "image":
        return "gemini" if provider.api_format == "gemini_official" else "openai"
    if "api.openai.com" in base:
        return "openai"
    if "googleapis.com" in base:
        return "gemini"
    return "unified"


def concurrency(role: str) -> int:
    """该用途可用的并发数：每个 Key 一路（与旧版按 Key 数量并发的行为一致）。"""
    try:
        return max(1, len(resolve(role).provider.api_keys))
    except NotConfiguredError:
        return 1


# ========== API Key 轮询 ==========
# 同一服务商的多个 Key 轮流使用；连续失败 3 次的 Key 暂时跳过，全部失败后重置。

_key_lock = threading.Lock()
_next_index: dict[str, int] = {}
_failures: dict[tuple[str, str], int] = {}
_MAX_CONSECUTIVE_FAILURES = 3


def pick_key(provider: Provider) -> str:
    keys = provider.api_keys
    if not keys:
        return ""  # 本地服务（Ollama 等）可以不填 Key
    with _key_lock:
        start = _next_index.get(provider.id, 0)
        for offset in range(len(keys)):
            idx = (start + offset) % len(keys)
            if _failures.get((provider.id, keys[idx]), 0) < _MAX_CONSECUTIVE_FAILURES:
                _next_index[provider.id] = idx + 1
                return keys[idx]
        for key in keys:
            _failures.pop((provider.id, key), None)
        _next_index[provider.id] = start + 1
        return keys[start % len(keys)]


def report_key(provider: Provider, key: str, ok: bool) -> None:
    if not key:
        return
    with _key_lock:
        if ok:
            _failures.pop((provider.id, key), None)
        else:
            _failures[(provider.id, key)] = _failures.get((provider.id, key), 0) + 1
