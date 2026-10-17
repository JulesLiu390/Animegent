"""统一的 LLM 调用层（参考 PetGPT 的 llm 适配层），支持三种 API 格式：

- openai_compatible：OpenAI Chat Completions（OpenAI、DeepSeek、OpenRouter、Ollama、各类中转站…）
- gemini_official：Google Gemini generateContent（官方或兼容的中转站）
- anthropic_native：Anthropic Messages API

内部统一用一种与服务商无关的消息格式，发请求时由各 adapter 转换。Agent 的对话历史也直接存这个格式：
    {"role": "user" | "model", "parts": [part, ...]}
    part:
      {"type": "text", "text": str, "thought_signature"?: str}
      {"type": "image", "path": str} 或 {"type": "image", "data": base64, "mime_type": str}
      （text / image 可以带 "observation": True：附在工具结果后面给模型看的内容，不算用户的新消息）
      {"type": "function_call", "id": str, "name": str, "args": dict, "thought_signature"?: str}
      {"type": "function_response", "id": str, "name": str, "response": dict}
工具声明：{"name": str, "description": str, "parameters": JSON Schema}
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable, Iterator
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from src.providers import settings as provider_settings
from src.providers.http import (
    ProviderError,
    ProviderHTTPError,
    anthropic_base,
    gemini_root,
    http_client,
    is_transient,
    iter_payloads,
    load_llm_image,
    openai_base,
    parse_json_text,
    raise_for_status,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Gemini 3 会校验当前轮 functionCall 的 thought signature；历史里缺签名时（例如这一轮中途换过服务商）
# 用官方文档给出的占位值跳过校验
_GEMINI_DUMMY_SIGNATURE = "skip_thought_signature_validator"
_ANTHROPIC_VERSION = "2023-06-01"
_ANTHROPIC_MAX_TOKENS = 8192


# ========== 对外接口 ==========

def stream_chat(
    role: str,
    system: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    *,
    model: str | None = None,
    timeout: float = 180.0,
    max_retries: int = 3,
) -> Iterator[dict]:
    """流式对话：先逐段产出 {"type": "text", "text": 增量}，最后产出 {"type": "message", "message": 模型消息}。

    还没输出任何内容时遇到网络错误、限流或 5xx，会换一个 Key 重试。
    """
    endpoint = provider_settings.resolve(role, model)
    yield from _with_retries(
        endpoint, max_retries,
        lambda key: _stream_once(endpoint, key, system, messages, tools, None, timeout),
    )


def chat(
    role: str,
    system: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    *,
    model: str | None = None,
    timeout: float = 180.0,
) -> dict:
    """非流式对话，返回模型消息。"""
    message: dict | None = None
    for event in stream_chat(role, system, messages, tools, model=model, timeout=timeout):
        if event["type"] == "message":
            message = event["message"]
    return message or {"role": "model", "parts": []}


def generate_json(
    role: str,
    parts: list[dict | str],
    schema: type[T],
    *,
    system: str = "",
    model: str | None = None,
    max_retries: int = 3,
    timeout: float = 180.0,
) -> T:
    """让模型按 Pydantic schema 输出 JSON 并校验，格式不对会重试。"""
    endpoint = provider_settings.resolve(role, model)
    json_schema = schema.model_json_schema()
    instruction = (
        "只输出一个符合下面 JSON Schema 的 JSON 对象，不要输出 Markdown 代码块或其他文字。\n"
        + json.dumps(json_schema, ensure_ascii=False)
    )
    system_text = f"{system}\n\n{instruction}" if system else instruction
    messages = [{"role": "user", "parts": [{"type": "text", "text": p} if isinstance(p, str) else p for p in parts]}]

    provider = endpoint.provider
    json_mode = True  # OpenAI 的 response_format / Gemini 的 responseSchema
    last_error: Exception | None = None
    delay = 2.0
    for attempt in range(1, max_retries + 1):
        key = provider_settings.pick_key(provider)
        try:
            text = "".join(
                event["text"]
                for event in _stream_once(endpoint, key, system_text, messages, None, json_schema, timeout, json_mode)
                if event["type"] == "text"
            )
            result = schema.model_validate(parse_json_text(text))
            provider_settings.report_key(provider, key, ok=True)
            return result
        except ProviderHTTPError as exc:
            last_error = exc
            if exc.status in (400, 422) and json_mode and endpoint.format != "anthropic_native":
                json_mode = False  # 部分兼容接口不支持结构化输出参数，退回只靠提示词约束
                continue
            if exc.retryable or exc.is_auth_error:
                provider_settings.report_key(provider, key, ok=False)
            if not (exc.retryable or (exc.is_auth_error and len(provider.api_keys) > 1)):
                break
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc  # 模型输出的 JSON 不合格，重试
        except Exception as exc:
            last_error = exc
            if not is_transient(exc):
                break
            provider_settings.report_key(provider, key, ok=False)
        if attempt < max_retries:
            logger.warning(f"[{provider.name} · {endpoint.model}] 结构化输出重试 {attempt}/{max_retries}: {last_error}")
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise ProviderError(f"[{provider.name} · {endpoint.model}] 结构化输出失败: {last_error}") from last_error


def fetch_models(api_format: str, base_url: str, api_key: str, timeout: float = 30.0) -> list[str]:
    """获取服务商的可用模型列表。"""
    with http_client(timeout) as client:
        if api_format == "gemini_official":
            models: list[str] = []
            page_token = None
            for _ in range(20):
                params: dict = {"pageSize": 1000}
                if page_token:
                    params["pageToken"] = page_token
                resp = client.get(f"{gemini_root(base_url)}/v1beta/models", params=params, headers=_gemini_headers(api_key))
                raise_for_status(resp)
                data = resp.json()
                models += [m["name"].removeprefix("models/") for m in data.get("models") or [] if m.get("name")]
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
            return sorted(set(models))

        if api_format == "anthropic_native":
            resp = client.get(f"{anthropic_base(base_url)}/models", params={"limit": 1000}, headers=_anthropic_headers(api_key))
            raise_for_status(resp)
            return sorted({m["id"] for m in resp.json().get("data") or [] if m.get("id")})

        # OpenAI 兼容：有的服务商要求 Base URL 带 /v1，有的不带，两个都试
        base = openai_base(base_url)
        urls = [f"{base}/models"]
        if not base.endswith("/v1"):
            urls.append(f"{base}/v1/models")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        last_error: Exception | None = None
        for url in urls:
            resp = client.get(url, headers=headers)
            try:
                raise_for_status(resp)
            except ProviderHTTPError as exc:
                last_error = exc
                if exc.status in (404, 405):
                    continue
                raise
            data = resp.json()
            items = data.get("data", []) if isinstance(data, dict) else data
            return sorted({str(m.get("id") if isinstance(m, dict) else m) for m in items or []})
        raise last_error or ProviderError("获取模型列表失败")


def ping(api_format: str, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> str:
    """用一句 hi 测试模型是否可用，返回模型回复的开头。"""
    provider = provider_settings.Provider(name="test", api_format=api_format, base_url=base_url)
    endpoint = provider_settings.Endpoint(role="chat", provider=provider, model=model, format=api_format)
    messages = [{"role": "user", "parts": [{"type": "text", "text": "hi"}]}]
    text = "".join(
        event["text"]
        for event in _stream_once(endpoint, api_key, "", messages, None, None, timeout)
        if event["type"] == "text"
    )
    return text[:200]


# ========== 请求与重试 ==========

def _with_retries(
    endpoint: provider_settings.Endpoint,
    max_retries: int,
    run: Callable[[str], Iterator[dict]],
) -> Iterator[dict]:
    provider = endpoint.provider
    delay = 2.0
    for attempt in range(1, max_retries + 1):
        key = provider_settings.pick_key(provider)
        emitted = False
        try:
            for event in run(key):
                if event["type"] == "text":
                    emitted = True
                yield event
            provider_settings.report_key(provider, key, ok=True)
            return
        except Exception as exc:
            auth_error = isinstance(exc, ProviderHTTPError) and exc.is_auth_error
            if is_transient(exc) or auth_error:
                provider_settings.report_key(provider, key, ok=False)
            can_retry = is_transient(exc) or (auth_error and len(provider.api_keys) > 1)
            if emitted or not can_retry or attempt == max_retries:
                exc.args = (f"[{provider.name} · {endpoint.model}] {exc}",)
                raise
            logger.warning(f"[{provider.name} · {endpoint.model}] 请求失败，{delay:.0f}s 后重试 ({attempt}/{max_retries}): {exc}")
            time.sleep(delay)
            delay = min(delay * 2, 30)


def _stream_once(
    endpoint: provider_settings.Endpoint,
    key: str,
    system: str,
    messages: list[dict],
    tools: list[dict] | None,
    json_schema: dict | None,
    timeout: float,
    json_mode: bool = True,
) -> Iterator[dict]:
    adapter = _ADAPTERS.get(endpoint.format)
    if adapter is None:
        raise ProviderError(f"不支持的 API 格式: {endpoint.format}")
    url, headers, body = adapter.build_request(
        endpoint.model, endpoint.provider.base_url, key, system,
        _prepare_history(messages), tools, json_schema if json_mode else None,
    )
    with http_client(timeout) as client:
        with client.stream("POST", url, headers=headers, json=body) as resp:
            raise_for_status(resp)
            yield from adapter.parse_stream(iter_payloads(resp))


def _prepare_history(messages: list[dict]) -> list[dict]:
    """补全工具调用 id，并去掉没有配对的 function_call / function_response。

    OpenAI / Anthropic 要求每个工具调用后面紧跟对应结果，Gemini 3 也要求数量一致；
    旧版历史没有 id，或者中途出错留下了不完整的调用，这里统一修正，避免整段对话都请求失败。
    """
    out = [
        {"role": "model" if m.get("role") == "model" else "user", "parts": [dict(p) for p in m.get("parts") or []]}
        for m in messages
    ]
    for i, msg in enumerate(out):
        if msg["role"] != "model":
            continue
        calls = [p for p in msg["parts"] if p.get("type") == "function_call"]
        for j, call in enumerate(calls):
            call.setdefault("args", {})
            if not call.get("id"):
                call["id"] = f"call_{i}_{j}"
        nxt = out[i + 1] if i + 1 < len(out) and out[i + 1]["role"] == "user" else None
        if nxt is None:
            continue
        pending = [(c.get("name"), c["id"]) for c in calls]
        for part in nxt["parts"]:
            if part.get("type") == "function_response" and not part.get("id"):
                idx = next((k for k, (name, _) in enumerate(pending) if name == part.get("name")), None)
                if idx is not None:
                    part["id"] = pending.pop(idx)[1]

    for i, msg in enumerate(out):
        if msg["role"] == "model":
            nxt = out[i + 1] if i + 1 < len(out) and out[i + 1]["role"] == "user" else None
            answered = {p.get("id") for p in (nxt["parts"] if nxt else []) if p.get("type") == "function_response"}
            msg["parts"] = [p for p in msg["parts"] if p.get("type") != "function_call" or p["id"] in answered]
        else:
            prev = out[i - 1] if i > 0 and out[i - 1]["role"] == "model" else None
            called = {p.get("id") for p in (prev["parts"] if prev else []) if p.get("type") == "function_call"}
            msg["parts"] = [p for p in msg["parts"] if p.get("type") != "function_response" or p.get("id") in called]
    return [m for m in out if m["parts"]]


def _new_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:12]}"


def _loads(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug(f"跳过无法解析的流式片段: {raw[:200]}")
        return None
    return data if isinstance(data, dict) else None


def _raise_payload_error(payload: dict) -> None:
    """有的服务商在 200 响应或流中返回 error 对象。"""
    err = payload.get("error")
    if not err or payload.get("type") not in (None, "error"):
        return
    message = err.get("message") if isinstance(err, dict) else str(err)
    text = json.dumps(err, ensure_ascii=False).lower()
    retryable = any(word in text for word in ("overloaded", "rate", "429", "500", "502", "503", "unavailable", "timeout"))
    raise ProviderError(message or text, retryable=retryable)


def _object_schema(params: dict | None) -> dict:
    schema = dict(params or {})
    schema.setdefault("type", "object")
    if schema["type"] == "object":
        schema.setdefault("properties", {})
    return schema


def _missing_image_text(part: dict) -> dict:
    return {"type": "text", "text": f"[图片已不存在: {part.get('path', '')}]"}


# ========== OpenAI 兼容 ==========

class _OpenAIAdapter:
    def build_request(self, model, base_url, key, system, messages, tools, json_schema):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body: dict = {"model": model, "messages": self._messages(system, messages), "stream": True}
        if tools:
            body["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": _object_schema(t.get("parameters")),
                }}
                for t in tools
            ]
            body["tool_choice"] = "auto"
        if json_schema is not None:
            body["response_format"] = {"type": "json_object"}
        return f"{openai_base(base_url)}/chat/completions", headers, body

    def _messages(self, system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        if system:
            out.append({"role": "system", "content": system})
        for msg in messages:
            if msg["role"] == "model":
                text = "".join(p.get("text", "") for p in msg["parts"] if p["type"] == "text")
                calls = [p for p in msg["parts"] if p["type"] == "function_call"]
                item: dict = {"role": "assistant", "content": text or None}
                if calls:
                    item["tool_calls"] = [
                        {"id": c["id"], "type": "function", "function": {
                            "name": c["name"], "arguments": json.dumps(c.get("args") or {}, ensure_ascii=False),
                        }}
                        for c in calls
                    ]
                if text or calls:
                    out.append(item)
                continue
            content: list[dict] = []
            for part in msg["parts"]:
                if part["type"] == "function_response":
                    out.append({
                        "role": "tool",
                        "tool_call_id": part["id"],
                        "content": json.dumps(part.get("response") or {}, ensure_ascii=False),
                    })
                elif part["type"] == "text" and part.get("text"):
                    content.append({"type": "text", "text": part["text"]})
                elif part["type"] == "image":
                    image = load_llm_image(part)
                    if image is None:
                        content.append(_missing_image_text(part))
                    else:
                        data, mime = image
                        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
            if content:
                only_text = len(content) == 1 and content[0]["type"] == "text"
                out.append({"role": "user", "content": content[0]["text"] if only_text else content})
        return out

    def parse_stream(self, payloads: Iterator[str]) -> Iterator[dict]:
        text: list[str] = []
        calls: dict[int, dict] = {}
        for raw in payloads:
            if raw == "[DONE]":
                break
            chunk = _loads(raw)
            if chunk is None:
                continue
            _raise_payload_error(chunk)
            for choice in chunk.get("choices") or []:
                # 流式是 delta；不支持流式的中转站直接返回完整的 message
                delta = choice.get("delta") or choice.get("message") or {}
                piece = delta.get("content")
                if isinstance(piece, str) and piece:
                    text.append(piece)
                    yield {"type": "text", "text": piece}
                for pos, tc in enumerate(delta.get("tool_calls") or []):
                    slot = calls.setdefault(tc.get("index", pos), {"id": "", "name": "", "arguments": ""})
                    slot["id"] = tc.get("id") or slot["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name") and not slot["name"]:
                        slot["name"] = fn["name"]
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        slot["arguments"] += args
                    elif isinstance(args, dict):
                        slot["arguments"] = json.dumps(args, ensure_ascii=False)

        parts: list[dict] = []
        if text:
            parts.append({"type": "text", "text": "".join(text)})
        for idx in sorted(calls):
            slot = calls[idx]
            if not slot["name"]:
                continue
            parts.append({
                "type": "function_call",
                "id": slot["id"] or _new_call_id(),
                "name": slot["name"],
                "args": _parse_arguments(slot["arguments"]),
            })
        yield {"type": "message", "message": {"role": "model", "parts": parts}}


def _parse_arguments(raw: str) -> dict:
    if not raw.strip():
        return {}
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"工具参数不是合法 JSON: {raw[:200]}")
        return {}
    return args if isinstance(args, dict) else {}


# ========== Gemini 官方 ==========

def _gemini_headers(key: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["x-goog-api-key"] = key
    return headers


def gemini_model_path(model: str) -> str:
    return model.removeprefix("models/")


# Gemini 的 Schema 是 OpenAPI 子集：type 用大写，不支持 $ref、title、additionalProperties 等字段
_GEMINI_SCHEMA_KEYS = {
    "format", "description", "nullable", "enum", "required", "minItems", "maxItems",
    "minimum", "maximum", "propertyOrdering",
}


def to_gemini_schema(schema: dict, defs: dict | None = None) -> dict:
    """JSON Schema（含 Pydantic 生成的 $defs/$ref）转成 Gemini 的 Schema。"""
    defs = schema.get("$defs", {}) if defs is None else defs
    if "$ref" in schema:
        ref = defs.get(schema["$ref"].rsplit("/", 1)[-1], {})
        return to_gemini_schema({**ref, **{k: v for k, v in schema.items() if k != "$ref"}}, defs)
    out: dict = {}
    for key, value in schema.items():
        if key == "type":
            if isinstance(value, list):
                non_null = [t for t in value if t != "null"]
                if len(non_null) < len(value):
                    out["nullable"] = True
                value = non_null[0] if non_null else "string"
            out["type"] = str(value).upper()
        elif key == "properties":
            out["properties"] = {name: to_gemini_schema(sub, defs) for name, sub in value.items()}
        elif key == "items":
            out["items"] = to_gemini_schema(value, defs)
        elif key == "anyOf":
            options = [o for o in value if o.get("type") != "null"]
            if len(options) < len(value):
                out["nullable"] = True
            if len(options) == 1:
                out.update(to_gemini_schema(options[0], defs))
            elif options:
                out["anyOf"] = [to_gemini_schema(o, defs) for o in options]
        elif key in _GEMINI_SCHEMA_KEYS:
            out[key] = value
    return out


class _GeminiAdapter:
    def build_request(self, model, base_url, key, system, messages, tools, json_schema):
        url = f"{gemini_root(base_url)}/v1beta/models/{gemini_model_path(model)}:streamGenerateContent?alt=sse"
        body: dict = {"contents": self._contents(model, messages)}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [{"functionDeclarations": [self._declaration(t) for t in tools]}]
            body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        if json_schema is not None:
            body["generationConfig"] = {
                "responseMimeType": "application/json",
                "responseSchema": to_gemini_schema(json_schema),
            }
        return url, _gemini_headers(key), body

    @staticmethod
    def _declaration(tool: dict) -> dict:
        decl = {"name": tool["name"], "description": tool.get("description", "")}
        params = tool.get("parameters") or {}
        # 没有参数的函数不能传空 properties 的 OBJECT，直接省略 parameters
        if params.get("properties") or params.get("type", "object") != "object":
            decl["parameters"] = to_gemini_schema(params)
        return decl

    def _contents(self, model: str, messages: list[dict]) -> list[dict]:
        # 当前轮：最后一条真正的用户消息（不是工具结果，也不是附在工具结果后面给模型看的图）之后
        turn_start = 0
        for i, msg in enumerate(messages):
            if msg["role"] == "user" and any(p["type"] != "function_response" and not p.get("observation") for p in msg["parts"]):
                turn_start = i
        needs_signature = "gemini-3" in model

        contents = []
        for i, msg in enumerate(messages):
            parts = []
            for part in msg["parts"]:
                kind = part["type"]
                if kind == "text":
                    if not part.get("text"):
                        continue
                    item = {"text": part["text"]}
                    if part.get("thought_signature"):
                        item["thoughtSignature"] = part["thought_signature"]
                elif kind == "image":
                    image = load_llm_image(part)
                    if image is None:
                        item = {"text": _missing_image_text(part)["text"]}
                    else:
                        data, mime = image
                        item = {"inlineData": {"mimeType": mime, "data": data}}
                elif kind == "function_call":
                    item = {"functionCall": {"name": part["name"], "args": part.get("args") or {}}}
                    signature = part.get("thought_signature")
                    if not signature and needs_signature and i > turn_start:
                        signature = _GEMINI_DUMMY_SIGNATURE
                    if signature:
                        item["thoughtSignature"] = signature
                elif kind == "function_response":
                    response = part.get("response")
                    item = {"functionResponse": {
                        "name": part["name"],
                        "response": response if isinstance(response, dict) else {"result": response},
                    }}
                else:
                    continue
                parts.append(item)
            if parts:
                contents.append({"role": msg["role"], "parts": parts})
        return contents

    def parse_stream(self, payloads: Iterator[str]) -> Iterator[dict]:
        text: list[str] = []
        text_signature = ""
        calls: list[dict] = []
        finish_reason = ""
        for raw in payloads:
            chunk = _loads(raw)
            if chunk is None:
                continue
            _raise_payload_error(chunk)
            feedback = chunk.get("promptFeedback") or {}
            if feedback.get("blockReason"):
                raise ProviderError(f"Gemini 拒绝了这个请求（{feedback['blockReason']}）")
            for candidate in (chunk.get("candidates") or [])[:1]:
                finish_reason = candidate.get("finishReason") or finish_reason
                for part in (candidate.get("content") or {}).get("parts") or []:
                    signature = part.get("thoughtSignature") or part.get("thought_signature") or ""
                    call = part.get("functionCall") or part.get("function_call")
                    if call:
                        item = {
                            "type": "function_call",
                            "id": call.get("id") or _new_call_id(),
                            "name": call.get("name", ""),
                            "args": call.get("args") or {},
                        }
                        if signature:
                            item["thought_signature"] = signature
                        calls.append(item)
                        continue
                    if signature:
                        text_signature = signature
                    if part.get("thought"):
                        continue  # 思考摘要不展示
                    if part.get("text"):
                        text.append(part["text"])
                        yield {"type": "text", "text": part["text"]}

        if not text and not calls and finish_reason not in ("", "STOP", "MAX_TOKENS"):
            # MALFORMED_FUNCTION_CALL 等偶发情况重试可能就好了；安全拦截类重试也没用
            retryable = finish_reason in ("MALFORMED_FUNCTION_CALL", "OTHER")
            raise ProviderError(f"Gemini 没有返回内容（finishReason={finish_reason}）", retryable=retryable)

        parts: list[dict] = []
        if text:
            item = {"type": "text", "text": "".join(text)}
            if text_signature:
                item["thought_signature"] = text_signature
            parts.append(item)
        parts.extend(calls)
        yield {"type": "message", "message": {"role": "model", "parts": parts}}


# ========== Anthropic 原生 ==========

def _anthropic_headers(key: str) -> dict:
    headers = {"Content-Type": "application/json", "anthropic-version": _ANTHROPIC_VERSION}
    if key:
        headers["x-api-key"] = key
    return headers


class _AnthropicAdapter:
    def build_request(self, model, base_url, key, system, messages, tools, json_schema):
        # Anthropic 没有通用的 JSON 输出参数，靠 generate_json 放进 system 的说明约束格式
        body: dict = {
            "model": model,
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
            "stream": True,
            "messages": self._messages(messages),
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {"name": t["name"], "description": t.get("description", ""), "input_schema": _object_schema(t.get("parameters"))}
                for t in tools
            ]
        return f"{anthropic_base(base_url)}/messages", _anthropic_headers(key), body

    def _messages(self, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for msg in messages:
            role = "assistant" if msg["role"] == "model" else "user"
            blocks: list[dict] = []
            for part in msg["parts"]:
                kind = part["type"]
                if kind == "text" and part.get("text"):
                    blocks.append({"type": "text", "text": part["text"]})
                elif kind == "image":
                    image = load_llm_image(part)
                    if image is None:
                        blocks.append(_missing_image_text(part))
                    else:
                        data, mime = image
                        blocks.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
                elif kind == "function_call":
                    blocks.append({"type": "tool_use", "id": part["id"], "name": part["name"], "input": part.get("args") or {}})
                elif kind == "function_response":
                    blocks.append({
                        "type": "tool_result",
                        "tool_use_id": part["id"],
                        "content": json.dumps(part.get("response") or {}, ensure_ascii=False),
                    })
            if not blocks:
                continue
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(blocks)  # 合并相邻的同角色消息
            else:
                out.append({"role": role, "content": blocks})
        return out

    def parse_stream(self, payloads: Iterator[str]) -> Iterator[dict]:
        blocks: dict[int, dict] = {}
        for raw in payloads:
            event = _loads(raw)
            if event is None:
                continue
            _raise_payload_error(event)
            kind = event.get("type")
            if kind == "message":
                # 不支持流式的中转站直接返回完整消息
                for idx, block in enumerate(event.get("content") or []):
                    if block.get("type") == "text" and block.get("text"):
                        blocks[idx] = {"kind": "text", "text": block["text"]}
                        yield {"type": "text", "text": block["text"]}
                    elif block.get("type") == "tool_use":
                        blocks[idx] = {"kind": "tool", "id": block.get("id"), "name": block.get("name"),
                                       "json": json.dumps(block.get("input") or {})}
            elif kind == "content_block_start":
                block = event.get("content_block") or {}
                idx = event.get("index", len(blocks))
                if block.get("type") == "text":
                    blocks[idx] = {"kind": "text", "text": block.get("text", "")}
                    if block.get("text"):
                        yield {"type": "text", "text": block["text"]}
                elif block.get("type") == "tool_use":
                    blocks[idx] = {"kind": "tool", "id": block.get("id"), "name": block.get("name"), "json": ""}
            elif kind == "content_block_delta":
                delta = event.get("delta") or {}
                block = blocks.get(event.get("index", -1))
                if block is None:
                    continue
                if delta.get("type") == "text_delta" and block["kind"] == "text":
                    block["text"] += delta.get("text", "")
                    if delta.get("text"):
                        yield {"type": "text", "text": delta["text"]}
                elif delta.get("type") == "input_json_delta" and block["kind"] == "tool":
                    block["json"] += delta.get("partial_json", "")
            elif kind == "message_stop":
                break

        parts: list[dict] = []
        text = "".join(b["text"] for _, b in sorted(blocks.items()) if b["kind"] == "text")
        if text:
            parts.append({"type": "text", "text": text})
        for _, block in sorted(blocks.items()):
            if block["kind"] == "tool" and block.get("name"):
                parts.append({
                    "type": "function_call",
                    "id": block.get("id") or _new_call_id(),
                    "name": block["name"],
                    "args": _parse_arguments(block["json"]),
                })
        yield {"type": "message", "message": {"role": "model", "parts": parts}}


_ADAPTERS = {
    "openai_compatible": _OpenAIAdapter(),
    "gemini_official": _GeminiAdapter(),
    "anthropic_native": _AnthropicAdapter(),
}
