"""Tests for src.web.serializer – Agent history <-> SQLite JSON."""

from src.web.serializer import history_entry_from_json, history_entry_to_json


def test_round_trip_keeps_text_and_tool_parts():
    entry = {
        "role": "model",
        "parts": [
            {"type": "text", "text": "好的，我来帮你检测人脸。", "thought_signature": "c2ln"},
            {"type": "function_call", "id": "call_1", "name": "detect_faces_in_image",
             "args": {"image_path": "/tmp/photo.jpg"}, "thought_signature": "c2ln"},
        ],
    }
    restored = history_entry_from_json(history_entry_to_json(entry))
    assert restored == entry


def test_function_response_round_trip():
    entry = {
        "role": "user",
        "parts": [{"type": "function_response", "id": "call_1", "name": "detect_faces_in_image",
                   "response": {"count": 2, "faces": [{"age": 25}]}}],
    }
    assert history_entry_from_json(history_entry_to_json(entry)) == entry


def test_inline_image_data_not_persisted():
    entry = {
        "role": "user",
        "parts": [
            {"type": "image", "data": "aGVsbG8=", "mime_type": "image/png"},
            {"type": "text", "text": "看看这张图"},
        ],
    }
    assert history_entry_to_json(entry)["parts"] == [{"type": "text", "text": "看看这张图"}]


def test_image_path_parts_persisted_without_duplication():
    entry = {
        "role": "user",
        "parts": [
            {"type": "text", "text": "[图片路径: /tmp/a.png]"},
            {"type": "image", "path": "/tmp/a.png"},
            {"type": "text", "text": "分析一下"},
        ],
    }
    restored = history_entry_from_json(history_entry_to_json(entry))
    assert restored == entry


def test_legacy_gemini_rows_restore_image_parts():
    """旧版数据：只有图片路径标记、没有 image part，function_call 也没有 id。"""
    legacy = {
        "role": "user",
        "parts": [
            {"type": "text", "text": "[图片路径: /tmp/old.png]"},
            {"type": "text", "text": "请帮我分析这张图"},
        ],
    }
    restored = history_entry_from_json(legacy)
    assert restored["parts"] == [
        {"type": "text", "text": "[图片路径: /tmp/old.png]"},
        {"type": "image", "path": "/tmp/old.png"},
        {"type": "text", "text": "请帮我分析这张图"},
    ]

    legacy_call = {"role": "model", "parts": [{"type": "function_call", "name": "list_files", "args": {}}]}
    assert history_entry_from_json(legacy_call) == legacy_call


def test_unknown_role_becomes_user():
    assert history_entry_from_json({"role": "function", "parts": []})["role"] == "user"
