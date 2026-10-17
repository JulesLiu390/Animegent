"""旧版对话（前端自己保存的界面消息 ui_messages）→ Turn / Step。

旧版没有记录每轮对应模型历史的哪一段，转换出来的 turn 标为 legacy：只用来显示，不能回退；
它们的模型历史（history_entries 里 turn_id 为空的部分）整段保留，作为之后对话的上下文。
"""

from __future__ import annotations

_IMAGE_PLACEHOLDERS = {"(图片)", "(image)"}
_STOPPED_ERRORS = {"stopped", "用户已停止", "Stopped by the user"}


def convert_ui_messages(messages: list[dict]) -> list[dict]:
    """返回 [{"input", "status", "error", "error_kind", "steps": [...]}]，按顺序。"""
    turns: list[dict] = []
    current: dict | None = None
    for msg in messages:
        if msg.get("role") == "user":
            user_turn = msg.get("turnId")
            if current is None or current["steps"] or (current["_user"] not in (None, user_turn)):
                current = _new_turn(user_turn)
                turns.append(current)
            current["_user"] = user_turn
            for att in msg.get("attachedImages") or []:
                current["input"]["attachments"].append({k: v for k, v in att.items() if k != "previewUrl"})
            text = msg.get("content") or ""
            if text and text not in _IMAGE_PLACEHOLDERS:
                sent = msg.get("sendText") or text
                current["input"]["text"] = sent
                if sent != text:
                    current["input"]["display"] = text
        else:
            if current is None:
                current = _new_turn(None)
                turns.append(current)
            current["steps"].extend(_assistant_steps(msg))
            if msg.get("error"):
                current.update(status="failed", error=str(msg["error"]), error_kind=msg.get("errorKind"))
            elif msg.get("stopped"):
                current["status"] = "cancelled"
    for turn in turns:
        turn.pop("_user", None)
    return turns


def _new_turn(user_turn: str | None) -> dict:
    return {
        "_user": user_turn,
        "input": {"text": "", "attachments": []},
        "status": "completed",
        "error": None,
        "error_kind": None,
        "steps": [],
    }


def _assistant_steps(msg: dict) -> list[dict]:
    tool_calls = msg.get("toolCalls") or []
    segments = msg.get("segments")
    if not segments:
        # 更早的版本没有记录文字和工具的先后：工具在前，文字在后
        segments = [{"kind": "tool", "at": i} for i in range(len(tool_calls))]
        if msg.get("content"):
            segments.append({"kind": "text", "text": msg["content"]})
    steps = []
    for seg in segments:
        if seg.get("kind") == "text":
            if (seg.get("text") or "").strip():
                steps.append({"kind": "message", "status": "completed", "text": seg["text"]})
        elif seg.get("kind") == "tool":
            at = seg.get("at")
            if isinstance(at, int) and 0 <= at < len(tool_calls):
                steps.append(_tool_step(tool_calls[at]))
    return steps


def _tool_step(tc: dict) -> dict:
    tool = tc.get("tool") or ""
    result = tc.get("result") if isinstance(tc.get("result"), dict) else {}
    error = result.get("error")
    if tc.get("pending") or error in _STOPPED_ERRORS:
        status = "cancelled"
    elif error:
        status = "failed"
    else:
        status = "completed"

    display: dict = {}
    if tc.get("images"):
        display["media"] = tc["images"]
    if tool == "propose_plan":
        display["plan"] = tc.get("plan") or {"status": "expired", "steps": result.get("steps") or []}
    if tool in ("select_characters", "select_faces"):
        display.update({k: result[k] for k in ("type", "options", "faces") if k in result})
        if tc.get("selection"):
            display["selection"] = tc["selection"]
    verdict = tc.get("verdict")
    return {
        "kind": "tool",
        "status": status,
        "tool": tool,
        "args": tc.get("args") or {},
        "result": result,
        "display": display or None,
        "verdict": verdict if verdict in ("accepted", "rejected", "revised") else None,
        "duration_ms": tc.get("duration_ms"),
    }
