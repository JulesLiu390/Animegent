"""Offline tests for src.providers (settings, LLM adapters, image & video generation).

HTTP 请求用 httpx.MockTransport 模拟各家接口，不需要真实 API Key。
"""

import base64
import io
import json
import threading

import httpx
import pytest
from pydantic import BaseModel

from src.providers import image, llm, video
from src.providers import settings as provider_settings
from src.providers.http import anthropic_base, api_root, gemini_root, openai_base


# ---- fixtures ----

@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """每个测试用独立的 settings.json / .env，不碰仓库里的配置。"""
    monkeypatch.setattr(provider_settings, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(provider_settings, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(provider_settings, "_cache", None)
    monkeypatch.setattr(provider_settings, "_cache_mtime", None)
    monkeypatch.setattr(provider_settings, "_next_index", {})
    monkeypatch.setattr(provider_settings, "_failures", {})
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("BASE_URL", raising=False)
    for module in (llm, image, video):
        monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    return tmp_path


def mock_http(monkeypatch, handler):
    def factory(timeout, connect=20.0):
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

    for module in (llm, image, video):
        monkeypatch.setattr(module, "http_client", factory)


def sse(*events: dict | str) -> httpx.Response:
    lines = [f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in events]
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(lines).encode())


def configure(api_format: str, role: str = "chat", model: str = "m", keys=("sk-test-key-1",), **assignment) -> provider_settings.Provider:
    provider = provider_settings.create_provider({
        "name": "P", "api_format": api_format, "base_url": "https://api.example.com", "api_keys": list(keys),
    })
    provider_settings.update_models({role: {"provider_id": provider.id, "model": model, **assignment}})
    return provider


def collect(events):
    events = list(events)
    text = "".join(e["text"] for e in events if e["type"] == "text")
    message = next(e["message"] for e in events if e["type"] == "message")
    return text, message


# ---- settings ----

def test_bootstrap_imports_legacy_env(isolated_settings):
    (isolated_settings / ".env").write_text("API_KEYS=k1,k2\nBASE_URL=https://yunwu.ai/v1\n")
    settings = provider_settings.load()
    assert len(settings.providers) == 1
    provider = settings.providers[0]
    assert provider.api_format == "gemini_official"
    assert provider.api_keys == ["k1", "k2"]
    assert (isolated_settings / "settings.json").exists()

    chat = provider_settings.resolve("chat")
    assert (chat.model, chat.format) == ("gemini-3-flash-preview", "gemini_official")
    assert provider_settings.resolve("image").format == "gemini"
    assert provider_settings.resolve("video").model == "grok-video-3"
    assert provider_settings.resolve("video").format == "unified"
    assert provider_settings.concurrency("chat") == 3  # 并发上限默认 3，和 Key 的数量无关


def test_unconfigured_role_raises_without_creating_file(isolated_settings):
    with pytest.raises(provider_settings.NotConfiguredError):
        provider_settings.resolve("chat")
    assert not (isolated_settings / "settings.json").exists()


def test_provider_crud_masks_keys_and_keeps_them_on_update():
    provider = provider_settings.create_provider({
        "name": "OpenAI", "api_format": "openai_compatible", "base_url": "https://api.openai.com/v1",
        "api_keys": ["sk-abcdefghijklmnop", " sk-abcdefghijklmnop ", "sk-zyxwvutsrqponmlk"],
    })
    view = provider_settings.public_dict()["providers"][0]
    assert "api_keys" not in view
    assert view["key_count"] == 2  # 去重、去空格
    assert view["key_previews"] == ["sk-abc…mnop", "sk-zyx…nmlk"]

    provider_settings.update_provider(provider.id, {"name": "Renamed", "api_keys": None})
    stored = provider_settings.load().provider(provider.id)
    assert stored.name == "Renamed" and len(stored.api_keys) == 2

    provider_settings.update_provider(provider.id, {"api_keys": ["sk-new"]})
    assert provider_settings.load().provider(provider.id).api_keys == ["sk-new"]

    provider_settings.update_models({"chat": {"provider_id": provider.id, "model": "gpt-4.1"}})
    assert provider_settings.delete_provider(provider.id)
    assert provider_settings.load().models.chat.provider_id == ""


def test_update_models_validates_format_and_provider():
    provider = provider_settings.create_provider({"name": "P", "api_format": "openai_compatible"})
    with pytest.raises(ValueError):
        provider_settings.update_models({"video": {"provider_id": provider.id, "model": "m", "format": "bogus"}})
    with pytest.raises(ValueError):
        provider_settings.update_models({"chat": {"provider_id": "missing", "model": "m"}})
    provider_settings.update_models({"image": {"provider_id": provider.id, "model": "gpt-image-1", "format": "openai"}})
    assert provider_settings.resolve("image").format == "openai"


def test_vision_falls_back_to_chat():
    configure("anthropic_native", model="claude-sonnet-4-5")
    vision = provider_settings.resolve("vision")
    assert (vision.model, vision.format) == ("claude-sonnet-4-5", "anthropic_native")


def test_pick_key_round_robin_skips_failing_keys():
    provider = provider_settings.Provider(name="P", api_keys=["a", "b", "c"])
    assert [provider_settings.pick_key(provider) for _ in range(4)] == ["a", "b", "c", "a"]
    for _ in range(3):
        provider_settings.report_key(provider, "b", ok=False)
    assert [provider_settings.pick_key(provider) for _ in range(3)] == ["c", "a", "c"]
    assert provider_settings.pick_key(provider_settings.Provider(name="local")) == ""


def test_concurrency_limit_is_a_provider_setting():
    provider = configure("openai_compatible")
    assert provider.max_concurrency == 3 and provider_settings.public_dict()["providers"][0]["max_concurrency"] == 3
    provider_settings.update_provider(provider.id, {"max_concurrency": 2})
    assert provider_settings.concurrency("chat") == 2
    provider_settings.update_provider(provider.id, {"name": "Renamed", "max_concurrency": None})  # 不传就保留
    assert provider_settings.concurrency("chat") == 2
    for bad in (0, 17):
        with pytest.raises(ValueError):
            provider_settings.update_provider(provider.id, {"max_concurrency": bad})


def run_together(target, count: int) -> None:
    threads = [threading.Thread(target=target) for _ in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)


class Gauge:
    """记录同时有几个请求在进行。"""

    def __init__(self):
        self.now = self.max = 0
        self.lock = threading.Lock()

    def __enter__(self):
        with self.lock:
            self.now += 1
            self.max = max(self.max, self.now)

    def __exit__(self, *exc):
        with self.lock:
            self.now -= 1


def test_llm_and_image_requests_wait_for_a_slot(monkeypatch):
    provider = configure("openai_compatible")
    provider_settings.update_models({"image": {"provider_id": provider.id, "model": "gpt-image-1"}})
    provider_settings.update_provider(provider.id, {"max_concurrency": 2})
    gauge = Gauge()

    def slow_stream(*args, **kwargs):
        with gauge:
            threading.Event().wait(0.05)  # time.sleep 被 fixture 换成了空操作
            yield {"type": "text", "text": '{"answer": "ok"}'}
            yield {"type": "message", "message": {"role": "model", "parts": [{"type": "text", "text": "ok"}]}}

    monkeypatch.setattr(llm, "_stream_once", slow_stream)
    run_together(lambda: llm.chat("chat", "", [{"role": "user", "parts": [{"type": "text", "text": "hi"}]}]), 5)
    assert gauge.max == 2 and gauge.now == 0

    class Answer(BaseModel):
        answer: str

    gauge.max = 0
    run_together(lambda: llm.generate_json("chat", ["hi"], Answer), 5)
    assert gauge.max == 2

    def slow_image(*args, **kwargs):
        with gauge:
            threading.Event().wait(0.05)
            return image.GeneratedImage(b"png", "image/png")

    monkeypatch.setattr(image, "_openai_images", slow_image)
    gauge.max = 0
    run_together(lambda: image.generate("cat"), 5)
    assert gauge.max == 2 and provider_settings.active_requests("image") == 0


def test_base_url_normalization():
    assert openai_base("https://yunwu.ai") == "https://yunwu.ai/v1"
    assert openai_base("https://api.deepseek.com/v1/") == "https://api.deepseek.com/v1"
    assert openai_base("https://open.bigmodel.cn/api/paas/v4") == "https://open.bigmodel.cn/api/paas/v4"
    assert openai_base("https://x.com/v1/chat/completions") == "https://x.com/v1"
    assert openai_base("") == "https://api.openai.com/v1"
    assert gemini_root("https://yunwu.ai/v1") == "https://yunwu.ai"
    assert gemini_root("https://generativelanguage.googleapis.com/v1beta/openai/") == "https://generativelanguage.googleapis.com"
    assert gemini_root("") == "https://generativelanguage.googleapis.com"
    assert anthropic_base("https://api.anthropic.com") == "https://api.anthropic.com/v1"
    assert api_root("https://yunwu.ai/v1") == "https://yunwu.ai"


# ---- LLM ----

TOOLS = [
    {"name": "list_files", "description": "列文件",
     "parameters": {"type": "object", "properties": {"directory": {"type": "string"}}, "required": ["directory"]}},
    {"name": "select_faces", "description": "选人脸", "parameters": {"type": "object", "properties": {}}},
]


def history_with_tool_round(image_path: str) -> list[dict]:
    return [
        {"role": "user", "parts": [
            {"type": "text", "text": f"[图片路径: {image_path}]"},
            {"type": "image", "path": image_path},
            {"type": "text", "text": "看看有哪些文件"},
        ]},
        {"role": "model", "parts": [{"type": "function_call", "id": "call_a", "name": "list_files", "args": {"directory": "."}}]},
        {"role": "user", "parts": [{"type": "function_response", "id": "call_a", "name": "list_files", "response": {"files": []}}]},
    ]


def test_openai_stream_with_tool_calls(monkeypatch, tmp_path):
    configure("openai_compatible", model="gpt-4.1")
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNGfake")
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return sse(
            {"choices": [{"delta": {"content": "我来"}}]},
            {"choices": [{"delta": {"content": "看看"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_x", "function": {"name": "list_files", "arguments": "{\"direc"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "tory\": \"out\"}"}}]}}]},
            "[DONE]",
        )

    mock_http(monkeypatch, handler)
    text, message = collect(llm.stream_chat("chat", "系统提示", history_with_tool_round(str(png)), TOOLS))

    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test-key-1"
    body = seen["body"]
    assert body["stream"] is True and body["tool_choice"] == "auto"
    assert body["tools"][1]["function"]["parameters"] == {"type": "object", "properties": {}}
    msgs = body["messages"]
    assert msgs[0] == {"role": "system", "content": "系统提示"}
    assert msgs[1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert msgs[2]["tool_calls"][0]["id"] == "call_a"
    assert msgs[3] == {"role": "tool", "tool_call_id": "call_a", "content": "{\"files\": []}"}

    assert text == "我来看看"
    assert message["parts"] == [
        {"type": "text", "text": "我来看看"},
        {"type": "function_call", "id": "call_x", "name": "list_files", "args": {"directory": "out"}},
    ]


def test_gemini_stream_keeps_thought_signatures(monkeypatch):
    configure("gemini_official", model="gemini-3-flash-preview")
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return sse(
            {"candidates": [{"content": {"role": "model", "parts": [{"text": "好的"}]}}]},
            {"candidates": [{"content": {"role": "model", "parts": [
                {"functionCall": {"name": "select_faces", "args": {}}, "thoughtSignature": "U0lH"},
            ]}, "finishReason": "STOP"}]},
        )

    mock_http(monkeypatch, handler)
    history = [
        {"role": "user", "parts": [{"type": "text", "text": "风格化"}]},
        # 当前轮里没有签名的调用（比如中途换过服务商）
        {"role": "model", "parts": [{"type": "function_call", "id": "c1", "name": "list_files", "args": {"directory": "."}}]},
        {"role": "user", "parts": [{"type": "function_response", "id": "c1", "name": "list_files", "response": {"files": []}}]},
    ]
    text, message = collect(llm.stream_chat("chat", "sys", history, TOOLS))

    assert seen["url"] == "https://api.example.com/v1beta/models/gemini-3-flash-preview:streamGenerateContent?alt=sse"
    assert seen["key"] == "sk-test-key-1"
    body = seen["body"]
    assert body["systemInstruction"] == {"parts": [{"text": "sys"}]}
    decls = body["tools"][0]["functionDeclarations"]
    assert decls[0]["parameters"]["type"] == "OBJECT"
    assert decls[0]["parameters"]["properties"]["directory"]["type"] == "STRING"
    assert "parameters" not in decls[1]  # 无参数函数不传空 OBJECT
    assert body["contents"][1]["parts"][0]["thoughtSignature"] == "skip_thought_signature_validator"
    assert body["contents"][2]["parts"][0]["functionResponse"]["name"] == "list_files"

    assert text == "好的"
    call = message["parts"][1]
    assert call["name"] == "select_faces" and call["thought_signature"] == "U0lH" and call["id"]


def test_tool_result_images_follow_the_tool_results():
    """工具画出的图（observation）附在工具结果后面：OpenAI 变成工具消息之后的一条用户消息，Gemini 不把它当成新的一轮。"""
    image = {"type": "image", "data": base64.b64encode(b"png").decode(), "mime_type": "image/png", "observation": True}
    history = [
        {"role": "user", "parts": [{"type": "text", "text": "画草图"}]},
        {"role": "model", "parts": [{"type": "function_call", "id": "c1", "name": "draw_with_pil", "args": {}}]},
        {"role": "user", "parts": [
            {"type": "function_response", "id": "c1", "name": "draw_with_pil", "response": {"output_path": "/p/a.png"}},
            {"type": "text", "text": "[draw_with_pil 画出的图: /p/a.png]", "observation": True},
            image,
        ]},
    ]
    messages = llm._OpenAIAdapter()._messages("", history)
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "user"]
    assert [c["type"] for c in messages[3]["content"]] == ["text", "image_url"]

    contents = llm._GeminiAdapter()._contents("gemini-3-flash-preview", history)
    # 调用仍算当前轮：缺签名时照样补上占位签名
    assert contents[1]["parts"][0]["thoughtSignature"] == "skip_thought_signature_validator"
    assert [next(iter(p)) for p in contents[2]["parts"]] == ["functionResponse", "text", "inlineData"]


def test_anthropic_stream_with_tool_use(monkeypatch, tmp_path):
    configure("anthropic_native", model="claude-sonnet-4-5")
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNGfake")
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return sse(
            {"type": "message_start", "message": {"id": "msg"}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "查一下"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "list_files", "input": {}}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"directory\":"}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": " \"a\"}"}},
            {"type": "content_block_stop", "index": 1},
            {"type": "message_stop"},
        )

    mock_http(monkeypatch, handler)
    text, message = collect(llm.stream_chat("chat", "sys", history_with_tool_round(str(png)), TOOLS))

    assert seen["url"] == "https://api.example.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-test-key-1"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    body = seen["body"]
    assert body["system"] == "sys" and body["max_tokens"] > 0
    assert body["tools"][0]["input_schema"]["required"] == ["directory"]
    assert body["messages"][0]["content"][1]["type"] == "image"
    assert body["messages"][1]["content"][0] == {"type": "tool_use", "id": "call_a", "name": "list_files", "input": {"directory": "."}}
    assert body["messages"][2]["content"][0]["type"] == "tool_result"

    assert text == "查一下"
    assert message["parts"][1] == {"type": "function_call", "id": "toolu_1", "name": "list_files", "args": {"directory": "a"}}


def test_prepare_history_pairs_legacy_calls_and_drops_orphans():
    history = [
        {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
        {"role": "model", "parts": [
            {"type": "function_call", "name": "list_files", "args": {}},
            {"type": "function_call", "name": "describe_image", "args": {}},
        ]},
        # 旧版历史：没有 id；describe_image 的结果缺失
        {"role": "user", "parts": [{"type": "function_response", "name": "list_files", "response": {}}]},
        {"role": "model", "parts": [{"type": "function_call", "id": "lost", "name": "x", "args": {}}]},
        {"role": "user", "parts": [{"type": "text", "text": "继续"}]},
    ]
    prepared = llm._prepare_history(history)
    calls = prepared[1]["parts"]
    assert [c["name"] for c in calls] == ["list_files"]
    assert prepared[2]["parts"][0]["id"] == calls[0]["id"]
    # 没有结果的调用被去掉，空消息也随之去掉
    assert [m["role"] for m in prepared] == ["user", "model", "user", "user"]


def test_stream_retries_transient_errors_with_next_key(monkeypatch):
    configure("openai_compatible", keys=("key-a", "key-b"))
    used = []

    def handler(request: httpx.Request):
        used.append(request.headers["authorization"])
        if len(used) == 1:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return sse({"choices": [{"delta": {"content": "ok"}}]}, "[DONE]")

    mock_http(monkeypatch, handler)
    text, _ = collect(llm.stream_chat("chat", "", [{"role": "user", "parts": [{"type": "text", "text": "hi"}]}]))
    assert text == "ok"
    assert used == ["Bearer key-a", "Bearer key-b"]


def test_non_sse_json_response_is_accepted(monkeypatch):
    """部分中转站无视 stream=true，直接返回完整 JSON。"""
    configure("openai_compatible")

    def handler(request: httpx.Request):
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "整段回复"}}]})

    mock_http(monkeypatch, handler)
    reply = llm.chat("chat", "", [{"role": "user", "parts": [{"type": "text", "text": "hi"}]}])
    assert reply["parts"] == [{"type": "text", "text": "整段回复"}]


class _Scene(BaseModel):
    description: str
    tags: list[str]


class _Analysis(BaseModel):
    scenes: list[_Scene]


def test_generate_json_openai_falls_back_without_response_format(monkeypatch):
    configure("openai_compatible", role="vision", model="local-model")
    bodies = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        bodies.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format is not supported"}})
        return sse({"choices": [{"delta": {"content": "```json\n{\"scenes\": [{\"description\": \"海边\", \"tags\": [\"sunset\"]}]}\n```"}}]}, "[DONE]")

    mock_http(monkeypatch, handler)
    result = llm.generate_json("vision", ["分析场景"], _Analysis)
    assert result.scenes[0].description == "海边"
    assert len(bodies) == 2
    assert "JSON Schema" in bodies[1]["messages"][0]["content"]


def test_generate_json_gemini_sends_resolved_schema(monkeypatch):
    configure("gemini_official", role="vision", model="gemini-2.5-flash-lite")
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content)
        payload = {"scenes": [{"description": "教室", "tags": []}]}
        return sse({"candidates": [{"content": {"parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}}]})

    mock_http(monkeypatch, handler)
    assert llm.generate_json("vision", ["x"], _Analysis).scenes[0].description == "教室"
    schema = seen["body"]["generationConfig"]["responseSchema"]
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert schema["type"] == "OBJECT"
    scene = schema["properties"]["scenes"]["items"]
    assert scene["type"] == "OBJECT" and scene["properties"]["tags"]["items"]["type"] == "STRING"
    assert "title" not in json.dumps(schema) and "$ref" not in json.dumps(schema)


def test_fetch_models_openai_tries_v1_fallback(monkeypatch):
    def handler(request: httpx.Request):
        if request.url.path == "/api/models":
            return httpx.Response(404)
        assert request.url.path == "/api/v1/models"
        return httpx.Response(200, json={"data": [{"id": "b-model"}, {"id": "a-model"}]})

    mock_http(monkeypatch, handler)
    assert llm.fetch_models("openai_compatible", "https://x.com/api", "k") == ["a-model", "b-model"]


# ---- image ----

PNG_B64 = base64.b64encode(b"\x89PNG-result").decode()


def test_openai_images_generation_and_edits(monkeypatch, tmp_path):
    configure("openai_compatible", role="image", model="gpt-image-1", format="openai")
    ref_a, ref_b = tmp_path / "a.png", tmp_path / "b.jpg"
    ref_a.write_bytes(b"\x89PNGa")
    ref_b.write_bytes(b"\xff\xd8jpg")
    requests = []

    def handler(request: httpx.Request):
        request.read()
        requests.append(request)
        return httpx.Response(200, json={"data": [{"b64_json": PNG_B64}]})

    mock_http(monkeypatch, handler)
    result = image.generate("一只猫", aspect_ratio="9:16")
    assert result.data == b"\x89PNG-result"
    gen = requests[0]
    assert gen.url.path == "/v1/images/generations"
    assert json.loads(gen.content) == {"model": "gpt-image-1", "prompt": "一只猫", "n": 1, "size": "1024x1536"}

    image.generate("把衣服换成红色", [ref_a, ref_b])
    edit = requests[1]
    assert edit.url.path == "/v1/images/edits"
    assert edit.content.count(b'name="image[]"') == 2
    assert b'name="size"\r\n\r\nauto' in edit.content


def test_gemini_image_retries_when_no_image(monkeypatch, tmp_path):
    configure("gemini_official", role="image", model="gemini-3.1-flash-image-preview")
    ref = tmp_path / "face.jpg"
    ref.write_bytes(b"\xff\xd8face")
    calls = []

    def handler(request: httpx.Request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "我不能画这个"}]}}]})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": "给你"}, {"inlineData": {"mimeType": "image/png", "data": PNG_B64}},
        ]}}]})

    mock_http(monkeypatch, handler)
    result = image.generate("风格化", [ref])
    assert result.data == b"\x89PNG-result" and result.text == "给你"
    assert len(calls) == 2
    parts = calls[0]["contents"][0]["parts"]
    assert parts[0]["inlineData"]["mimeType"] == "image/jpeg" and parts[1] == {"text": "风格化"}
    assert calls[0]["generationConfig"] == {"responseModalities": ["IMAGE", "TEXT"]}


def test_image_http_400_is_not_retried(monkeypatch):
    configure("openai_compatible", role="image", model="dall-e-3", format="openai")
    count = []

    def handler(request: httpx.Request):
        count.append(1)
        return httpx.Response(400, json={"error": {"message": "invalid size"}})

    mock_http(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="invalid size"):
        image.generate("x")
    assert len(count) == 1


# ---- video ----

def test_unified_video_create_poll_download(monkeypatch, tmp_path):
    configure("gemini_official", role="video", model="grok-video-3", format="unified")
    frame = tmp_path / "clip_1.png"
    frame.write_bytes(b"\x89PNGframe")
    polls = []
    seen = {}

    def handler(request: httpx.Request):
        if request.url.path == "/v1/video/create":
            seen["create"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "task:1"})
        if request.url.path == "/v1/video/query":
            polls.append(1)
            if len(polls) == 1:
                return httpx.Response(200, json={"status": "processing", "progress": "50%"})
            return httpx.Response(200, json={"status": "completed", "video_url": "https://cdn.example.com/v.mp4"})
        assert str(request.url) == "https://cdn.example.com/v.mp4"
        return httpx.Response(200, headers={"content-type": "video/mp4"}, content=b"MP4DATA")

    mock_http(monkeypatch, handler)
    path = video.generate_video("跑步", [str(frame)], output_dir=tmp_path / "videos")
    assert path.name == "task_1.mp4" and path.read_bytes() == b"MP4DATA"
    body = seen["create"]
    assert body["model"] == "grok-video-3" and body["size"] == "720P" and body["aspect_ratio"] == "16:9"
    assert body["images"][0].startswith("data:image/png;base64,")


def test_sora_video_resizes_reference(monkeypatch, tmp_path):
    from PIL import Image

    configure("openai_compatible", role="video", model="sora-2", format="openai")
    frame = tmp_path / "clip_1.png"
    Image.new("RGB", (1365, 768), "red").save(frame)
    seen = {}

    def handler(request: httpx.Request):
        request.read()
        if request.method == "POST":
            seen["create"] = request.content
            return httpx.Response(200, json={"id": "video_123", "status": "queued"})
        if request.url.path == "/v1/videos/video_123":
            return httpx.Response(200, json={"id": "video_123", "status": "completed"})
        assert request.url.path == "/v1/videos/video_123/content"
        return httpx.Response(200, headers={"content-type": "video/mp4"}, content=b"SORA")

    mock_http(monkeypatch, handler)
    path = video.generate_video("跑步", [str(frame)], output_dir=tmp_path / "videos")
    assert path.read_bytes() == b"SORA"
    content = seen["create"]
    assert b'name="size"\r\n\r\n1280x720' in content
    # Sora 要求参考图和视频尺寸一致：1365x768 的首帧应被裁剪缩放成 1280x720
    marker = content.index(b'name="input_reference"; filename="first_frame.png"')
    start = content.index(b"\r\n\r\n", marker) + 4
    uploaded = Image.open(io.BytesIO(content[start:content.index(b"\r\n--", start)]))
    assert uploaded.size == (1280, 720)


def test_video_failure_message_includes_provider(monkeypatch, tmp_path):
    configure("gemini_official", role="video", model="veo3.1", format="unified")

    def handler(request: httpx.Request):
        if request.url.path == "/v1/video/create":
            return httpx.Response(200, json={"id": "t"})
        return httpx.Response(200, json={"status": "failed", "error": "content policy"})

    mock_http(monkeypatch, handler)
    with pytest.raises(Exception, match=r"\[P · veo3.1\].*content policy"):
        video.generate_video("x", output_dir=tmp_path)
