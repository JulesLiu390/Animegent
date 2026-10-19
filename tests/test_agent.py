"""Agent：用假的 LLM 和假的生成工具验证 turn / step 流程（离线）。

覆盖：普通回复和工具调用、讨论模式、生成前确认（批准 / 拒绝）、自动执行、后台任务和 check_jobs、
选择卡片、等用户时直接发新消息、停止、出错、画版式草图（画出的图给模型看一次）、写分镜草稿、分镜模式休眠。
"""

import dataclasses
import io
import json
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from src.providers import image as image_provider
from src.providers import llm
from src.providers import settings as provider_settings
from src.tools import pil_sandbox
from src.web import features
from src.web.agent import JobManager, Session
from src.web.agent.tools import base
from src.web.db import ConversationDB, new_id


class FakeLLM:
    """依次返回预设的模型回复（parts 列表，或 callable(messages) -> parts）；记录每次请求。"""

    def __init__(self, replies: list, delay: float = 0.0):
        self.replies = list(replies)
        self.delay = delay
        self.requests: list[dict] = []

    def __call__(self, role, system, messages, tools=None, **kwargs):
        self.requests.append({"system": system, "messages": [dict(m) for m in messages], "tools": [t["name"] for t in tools or []]})
        reply = self.replies.pop(0)
        parts = reply(messages) if callable(reply) else reply
        for part in parts:
            if part["type"] == "text":
                for chunk in part["text"].split("|"):
                    if self.delay:
                        time.sleep(self.delay)
                    yield {"type": "text", "text": chunk}
        yield {"type": "message", "message": {"role": "model", "parts": [
            {**p, "text": p["text"].replace("|", "")} if p["type"] == "text" else p for p in parts
        ]}}


def call(name: str, call_id: str, **args) -> dict:
    return {"type": "function_call", "id": call_id, "name": name, "args": args}


def text(value: str) -> dict:
    return {"type": "text", "text": value}


@pytest.fixture
def env(monkeypatch, tmp_path):
    root = tmp_path / "root"
    project = root / "projects" / "demo"
    for sub in ("input", "output/stylized", "output/faces", "output/panels", "output/scripts"):
        (project / sub).mkdir(parents=True)
    monkeypatch.setattr(base, "PROJECT_ROOT", root)
    monkeypatch.setattr(provider_settings, "resolve", lambda role, model=None: None)
    monkeypatch.setattr(provider_settings, "concurrency", lambda role: 2)
    db = ConversationDB(tmp_path / "test.db")
    jobs = JobManager(db)
    cid = db.create_conversation("demo")
    session = Session(db, jobs, cid, project)
    yield session
    db.close()


def use_llm(monkeypatch, replies: list, delay: float = 0.0) -> FakeLLM:
    fake = FakeLLM(replies, delay)
    monkeypatch.setattr(llm, "stream_chat", fake)
    return fake


def fake_tool(monkeypatch, name: str, run) -> None:
    monkeypatch.setitem(base._TOOLS, name, dataclasses.replace(base._TOOLS[name], run=run))


def fake_generate(monkeypatch, *, gate: threading.Event | None = None, error: str | None = None):
    """替换 generate_asset：真的写出一张图片（界面要拿到 URL），记录调用。"""
    calls: list[dict] = []
    active = {"now": 0, "max": 0}
    lock = threading.Lock()

    def run(args, ctx):
        with lock:
            calls.append(args)
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        try:
            if gate:
                gate.wait(5)
            else:
                time.sleep(0.05)
            if error:
                return {"error": error}
            out = Path(args["output_path"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"png")
            return {"output_path": str(out), "name": out.stem}
        finally:
            with lock:
                active["now"] -= 1

    fake_tool(monkeypatch, "generate_asset", run)
    return calls, active


def send(session: Session, message: str, interaction: str = "confirm", **kwargs) -> list[dict]:
    session.cancel_event.clear()
    with session.run_lock:
        return list(session.send(new_id(), {"text": message, "attachments": [], **kwargs}, lang="zh", mode="comic", interaction=interaction))


def resume(session: Session, turn_id: str, responses: dict, interaction: str = "confirm") -> list[dict]:
    session.cancel_event.clear()
    with session.run_lock:
        turn = session.db.get_turn(turn_id)
        return list(session.resume(turn, responses, lang="zh", mode="comic", interaction=interaction))


def last_turn(session: Session) -> dict:
    return session.db.last_turn(session.id)


def steps(session: Session, turn_id: str) -> list[dict]:
    return session.db.steps_for_turn(turn_id)


def roles(history: list[dict]) -> list[str]:
    out = []
    for entry in history:
        kinds = {p["type"] for p in entry["parts"]}
        out.append("call" if "function_call" in kinds else "result" if "function_response" in kinds else entry["role"])
    return out


# ---- 基本流程 ----


def test_text_reply_is_a_message_step(env, monkeypatch):
    use_llm(monkeypatch, [[text("你|好")]])
    events = send(env, "hi")
    turn = last_turn(env)
    assert turn["status"] == "completed"
    [step] = steps(env, turn["id"])
    assert (step["kind"], step["text"]) == ("message", "你好")
    assert [e["text"] for e in events if e["event"] == "delta"] == ["你", "好"]
    assert roles(env.db.get_history(env.id)) == ["user", "model"]


def test_tool_round_records_steps_and_history(env, monkeypatch):
    fake = use_llm(monkeypatch, [[text("看看文件"), call("list_files", "c1", directory="output")], [text("有这些")]])
    send(env, "有哪些素材")
    turn = last_turn(env)
    message, tool, summary = steps(env, turn["id"])
    assert tool["tool"] == "list_files" and tool["status"] == "completed"
    assert tool["result"]["directory"].endswith("projects/demo/output")  # 相对路径按项目目录解析
    assert (message["text"], summary["text"]) == ("看看文件", "有这些")
    history = env.db.get_history(env.id)
    assert roles(history) == ["user", "call", "result", "model"]
    assert history[2]["parts"][0]["id"] == "c1"
    assert "propose_plan" not in fake.requests[0]["tools"] and "check_jobs" in fake.requests[0]["tools"]


def test_user_images_are_sent_by_path(env, monkeypatch):
    image = env.project_dir / "input" / "a.png"
    image.write_bytes(b"png")
    fake = use_llm(monkeypatch, [[text("看到了")]])
    send(env, "看图", attachments=[{"path": str(image), "name": "a.png"}, {"path": "/x.md", "name": "x.md", "fileType": "markdown", "content": "# 剧本"}])
    parts = fake.requests[0]["messages"][0]["parts"]
    assert parts[0] == {"type": "text", "text": f"[图片路径: {image}]"}
    assert parts[1] == {"type": "image", "path": str(image)}
    assert parts[2]["text"].startswith("[附件: x.md (Markdown) /x.md]\n# 剧本") and parts[2]["text"].endswith("看图")


def test_ask_mode_only_offers_read_tools(env, monkeypatch):
    fake = use_llm(monkeypatch, [[call("write_script", "w1", file_path="a.md", content="x")], [text("好的")]])
    send(env, "写剧本", interaction="ask")
    turn = last_turn(env)
    tool = steps(env, turn["id"])[0]
    assert tool["status"] == "failed" and "讨论模式" in tool["result"]["error"]
    assert not (env.project_dir / "a.md").exists()
    assert set(fake.requests[0]["tools"]) == {
        "read_script", "list_files", "skill_load", "skill_read_resource", "describe_image", "review_comic_strip", "read_through",
        "check_jobs",
    }
    assert "讨论" in fake.requests[0]["system"]


def test_unconfigured_chat_fails_before_touching_history(env, monkeypatch):
    def not_configured(role, model=None):
        raise provider_settings.NotConfiguredError("还没有配置对话模型")

    monkeypatch.setattr(provider_settings, "resolve", not_configured)
    send(env, "hi")
    turn = last_turn(env)
    assert (turn["status"], turn["error_kind"]) == ("failed", "config")
    assert env.db.get_history(env.id) == []


def test_tool_exception_becomes_error_result(env, monkeypatch):
    def broken(args, ctx):
        raise KeyError("file_path")

    fake_tool(monkeypatch, "read_script", broken)
    use_llm(monkeypatch, [[call("read_script", "r1")], [text("读取失败了")]])
    send(env, "读剧本")
    tool = steps(env, last_turn(env)["id"])[0]
    assert tool["status"] == "failed" and tool["result"] == {"error": "KeyError: 'file_path'"}
    assert last_turn(env)["status"] == "completed"


# ---- 生成前确认 / 后台任务 ----


def test_generation_waits_for_approval_then_runs_in_background(env, monkeypatch):
    calls, _ = fake_generate(monkeypatch)
    fake = use_llm(monkeypatch, [
        [text("开始画"), call("generate_asset", "g1", prompt="猫", output_path="output/stylized/cat.png")],
        lambda messages: [call("check_jobs", "k1", job_ids=[messages[-1]["parts"][0]["response"]["job_id"]], wait_seconds=5)],
        [text("画好了")],
    ])
    send(env, "画一只猫")
    turn = last_turn(env)
    assert turn["status"] == "awaiting_approval"
    pending = steps(env, turn["id"])[1]
    assert pending["status"] == "pending_approval" and calls == []
    assert roles(env.db.get_history(env.id)) == ["user", "call"]  # 结果等批准后才写入

    events = resume(env, turn["id"], {pending["id"]: {"approve": True}})
    assert last_turn(env)["status"] == "completed"
    assert len(calls) == 1 and calls[0]["output_path"].endswith("projects/demo/output/stylized/cat.png")
    generate, check = steps(env, turn["id"])[1:3]
    job = env.db.get_job(generate["job_id"])
    assert generate["status"] == "completed" and generate["result"]["job_id"] == job["id"]
    assert job["status"] == "succeeded" and job["media"][0]["url"].startswith("/files/projects/demo/output/stylized/cat.png?v=")
    report = check["result"]
    assert report["unfinished"] == 0 and report["jobs"][0]["result"]["output_path"].endswith("cat.png")
    assert any(e["event"] == "job" and e["job"]["status"] == "succeeded" for e in events) or job["status"] == "succeeded"
    assert roles(fake.requests[-1]["messages"]) == ["user", "call", "result", "call", "result"]


def test_rejected_generation_is_reported_to_the_model(env, monkeypatch):
    calls, _ = fake_generate(monkeypatch)
    fake = use_llm(monkeypatch, [[call("generate_asset", "g1", prompt="猫", output_path="output/stylized/cat.png")], [text("好的，换个画法")]])
    send(env, "画一只猫")
    turn = last_turn(env)
    pending = steps(env, turn["id"])[0]
    resume(env, turn["id"], {pending["id"]: {"approve": False, "note": "要橘猫"}})
    assert calls == []
    assert steps(env, turn["id"])[0]["status"] == "rejected"
    response = fake.requests[-1]["messages"][-1]["parts"][0]["response"]
    assert "没有批准" in response["error"] and "要橘猫" in response["error"]
    assert last_turn(env)["status"] == "completed"


def test_auto_mode_runs_generation_without_approval(env, monkeypatch):
    calls, active = fake_generate(monkeypatch)
    use_llm(monkeypatch, [
        [call("generate_asset", f"g{i}", prompt=str(i), output_path=f"output/stylized/{i}.png") for i in range(3)],
        [call("check_jobs", "k1", wait_seconds=5)],
        [text("三张都好了")],
    ])
    send(env, "画三张", interaction="auto")
    turn = last_turn(env)
    assert turn["status"] == "completed" and len(calls) == 3
    assert active["max"] <= 2  # 并发数按服务商的并发上限（这里是 2）
    check = steps(env, turn["id"])[3]
    assert [j["status"] for j in check["result"]["jobs"]] == ["succeeded"] * 3


def test_failed_job_is_reported_by_check_jobs(env, monkeypatch):
    fake_generate(monkeypatch, error="额度不足")
    use_llm(monkeypatch, [
        [call("generate_asset", "g1", prompt="猫", output_path="output/stylized/cat.png")],
        [call("check_jobs", "k1", wait_seconds=5)],
        [text("生成失败了")],
    ])
    send(env, "画", interaction="auto")
    check = steps(env, last_turn(env)["id"])[1]
    [job] = check["result"]["jobs"]
    assert (job["status"], job["error"]) == ("failed", "额度不足")


def test_check_jobs_can_return_as_soon_as_one_job_finishes(env, monkeypatch):
    slow = threading.Event()

    def run(args, ctx):
        if args["prompt"] == "慢":
            slow.wait(5)
        out = Path(args["output_path"])
        out.write_bytes(b"png")
        return {"output_path": str(out), "name": out.stem}

    fake_tool(monkeypatch, "generate_asset", run)
    use_llm(monkeypatch, [
        [call("generate_asset", "g1", prompt="快", output_path="output/stylized/a.png"),
         call("generate_asset", "g2", prompt="慢", output_path="output/stylized/b.png")],
        [call("check_jobs", "k1", wait_seconds=20, until="any")],
        [text("先看第一张")],
    ])
    started = time.monotonic()
    try:
        send(env, "画两张", interaction="auto")
        check = steps(env, last_turn(env)["id"])[2]
        statuses = sorted(j["status"] for j in check["result"]["jobs"])
        assert statuses == ["running", "succeeded"] and check["result"]["unfinished"] == 1
        assert time.monotonic() - started < 4  # 没有等慢的那一张
    finally:
        slow.set()
        env.jobs.wait(env.id, None, turn_id=None, timeout=5)  # 等慢的那张写完再关数据库


def test_check_jobs_without_ids_reports_this_turn(env, monkeypatch):
    use_llm(monkeypatch, [[call("check_jobs", "k1", wait_seconds=0)], [text("没有任务")]])
    send(env, "好了吗")
    check = steps(env, last_turn(env)["id"])[0]
    assert check["result"] == {"jobs": [], "unfinished": 0, "message": "没有后台任务。"}


# ---- 选择卡片 ----


def test_character_selection_is_the_tool_result(env, monkeypatch):
    for name in ("a", "b"):
        (env.project_dir / "output" / "stylized" / f"{name}.png").write_bytes(b"png")
    a_path = str(env.project_dir / "output" / "stylized" / "a.png")
    fake = use_llm(monkeypatch, [[call("select_characters", "s1", preselected=[{"path": "output/stylized/a.png", "label": "小明"}])], [text("开始写剧本")]])
    send(env, "用小明画条漫")
    turn = last_turn(env)
    assert turn["status"] == "awaiting_input"
    step = steps(env, turn["id"])[0]
    options = {o["path"]: o for o in step["display"]["options"]}
    assert options[a_path]["selected"] and options[a_path]["label"] == "小明" and options[a_path]["url"].startswith("/files/projects/demo/")

    resume(env, turn["id"], {step["id"]: {"value": {"selected": [{"path": a_path, "label": "阿明"}]}}})
    result = fake.requests[-1]["messages"][-1]["parts"][0]["response"]
    assert result["selected"] == [{"path": a_path, "name": "a", "label": "阿明"}]
    assert last_turn(env)["status"] == "completed"


def test_face_selection_can_be_skipped(env, monkeypatch):
    (env.project_dir / "output" / "faces" / "f.png").write_bytes(b"png")
    fake = use_llm(monkeypatch, [[call("select_faces", "s1")], [text("好的，不风格化")]])
    send(env, "风格化")
    turn = last_turn(env)
    step = steps(env, turn["id"])[0]
    resume(env, turn["id"], {step["id"]: {"value": {"skipped": True}}})
    assert fake.requests[-1]["messages"][-1]["parts"][0]["response"]["skipped"] is True


def test_selection_without_choices_goes_straight_to_the_model(env, monkeypatch):
    use_llm(monkeypatch, [[call("select_faces", "s1")], [text("先上传照片吧")]])
    send(env, "风格化")
    turn = last_turn(env)
    assert turn["status"] == "completed"
    assert steps(env, turn["id"])[0]["result"]["faces"] == []


def test_new_message_while_waiting_settles_the_previous_turn(env, monkeypatch):
    fake_generate(monkeypatch)
    fake = use_llm(monkeypatch, [[call("generate_asset", "g1", prompt="猫", output_path="output/stylized/cat.png")], [text("好，不画了")]])
    send(env, "画一只猫")
    first = last_turn(env)
    send(env, "算了，先聊聊剧情")
    assert env.db.get_turn(first["id"])["status"] == "completed"
    assert steps(env, first["id"])[0]["status"] == "cancelled"
    messages = fake.requests[-1]["messages"]
    assert roles(messages) == ["user", "call", "result", "user"]
    assert "直接发送了新消息" in messages[2]["parts"][0]["response"]["error"]


# ---- 停止 ----


def test_stop_during_stream_keeps_partial_text(env, monkeypatch):
    use_llm(monkeypatch, [[text("第一段|第二段|第三段|第四段")]], delay=0.15)
    session = env

    def stop_soon():
        time.sleep(0.4)
        session.stop()

    threading.Thread(target=stop_soon).start()
    started = time.time()
    send(session, "讲个故事")
    assert time.time() - started < 1.5
    turn = last_turn(session)
    assert turn["status"] == "cancelled"
    [message] = steps(session, turn["id"])
    assert message["text"].startswith("第一段") and message["text"] != "第一段第二段第三段第四段"
    history = session.db.get_history(session.id)
    assert roles(history) == ["user", "model"] and history[-1]["parts"][0]["text"] == message["text"]


def test_stop_while_waiting_for_jobs(env, monkeypatch):
    gate = threading.Event()
    fake_generate(monkeypatch, gate=gate)
    use_llm(monkeypatch, [
        [call("generate_asset", "g1", prompt="猫", output_path="output/stylized/cat.png")],
        [call("check_jobs", "k1", wait_seconds=60)],
    ])
    threading.Timer(0.5, env.stop).start()
    started = time.time()
    send(env, "画", interaction="auto")
    assert time.time() - started < 3
    turn = last_turn(env)
    assert turn["status"] == "cancelled"
    check = steps(env, turn["id"])[1]
    assert check["status"] == "cancelled"
    # 已经开始生成的图片照常完成
    gate.set()
    job_id = steps(env, turn["id"])[0]["job_id"]
    for _ in range(50):
        if env.db.get_job(job_id)["status"] == "succeeded":
            break
        time.sleep(0.05)
    assert env.db.get_job(job_id)["status"] == "succeeded"
    assert roles(env.db.get_history(env.id)) == ["user", "call", "result", "call", "result"]


def test_stop_while_waiting_for_approval(env, monkeypatch):
    fake_generate(monkeypatch)
    use_llm(monkeypatch, [[call("generate_asset", "g1", prompt="猫", output_path="output/stylized/cat.png")]])
    send(env, "画")
    turn = last_turn(env)
    with env.run_lock:
        list(env.settle("用户已停止"))
    assert env.db.get_turn(turn["id"])["status"] == "cancelled"
    assert roles(env.db.get_history(env.id)) == ["user", "call", "result"]


def test_restart_marks_unfinished_jobs_failed(env):
    env.db.create_job("job_old", env.id, None, None, "generate_asset", {})
    JobManager(env.db).recover()
    assert env.db.get_job("job_old")["status"] == "failed"


# ---- 画版式草图 ----


def fake_sandbox(monkeypatch, *, error: str | None = None) -> list[dict]:
    """替换 PIL 沙箱（不需要 Deno）：返回一张真的 PNG，记录调用。"""
    calls: list[dict] = []

    def run(code, width=900, height=1600, *, timeout=30.0):
        calls.append({"code": code, "width": width, "height": height})
        if error:
            return pil_sandbox.RunResult(ok=False, error=error)
        buf = io.BytesIO()
        Image.new("RGB", (width, height), "white").save(buf, "PNG")
        return pil_sandbox.RunResult(ok=True, png=buf.getvalue(), size=(width, height))

    monkeypatch.setattr(pil_sandbox, "run", run)
    return calls


def test_drawn_sketch_is_shown_to_the_model_once(env, monkeypatch):
    calls = fake_sandbox(monkeypatch)
    code = "draw.rectangle([20, 20, W - 20, 400], outline='black', width=6)"
    fake = use_llm(monkeypatch, [
        [text("先画版式"), call("draw_with_pil", "d1", code=code, output_path="output/layouts/strip_1.png")],
        [text("草图没问题")],
        [text("好的")],
    ])
    send(env, "画第一条的版式")  # 生成前确认模式下也直接执行，不用批准
    turn = last_turn(env)
    assert turn["status"] == "completed"
    tool = steps(env, turn["id"])[1]
    layouts = env.project_dir / "output" / "layouts"
    assert tool["status"] == "completed" and tool["display"]["media"][0]["path"] == str(layouts / "strip_1.png")
    assert (layouts / "strip_1.png").is_file() and (layouts / "strip_1.py").read_text() == code
    assert calls == [{"code": code, "width": 900, "height": 1600}]

    # 下一次请求里，工具结果后面附着画出来的图
    parts = fake.requests[1]["messages"][-1]["parts"]
    assert [p["type"] for p in parts] == ["function_response", "text", "image"]
    assert parts[2] == {"type": "image", "path": str(layouts / "strip_1.png"), "observation": True}
    # 图片不写进历史，之后的请求不再重发
    assert all(p["type"] != "image" for entry in env.db.get_history(env.id) for p in entry["parts"])
    send(env, "继续")
    assert all(p["type"] != "image" for m in fake.requests[2]["messages"] for p in m["parts"])


def test_sketch_code_error_goes_back_to_the_model(env, monkeypatch):
    fake_sandbox(monkeypatch, error='  File "<code>", line 1, in <module>\nNameError: name \'x\' is not defined')
    fake = use_llm(monkeypatch, [[call("draw_with_pil", "d1", code="x", output_path="output/layouts/a.png")], [text("我改一下")]])
    send(env, "画")
    tool = steps(env, last_turn(env)["id"])[0]
    assert tool["status"] == "failed" and "NameError" in tool["result"]["error"]
    assert not (env.project_dir / "output" / "layouts").exists()
    assert [p["type"] for p in fake.requests[1]["messages"][-1]["parts"]] == ["function_response"]


def test_sketch_must_stay_inside_the_project(env, monkeypatch):
    calls = fake_sandbox(monkeypatch)
    use_llm(monkeypatch, [[call("draw_with_pil", "d1", code="pass", output_path=str(env.project_dir.parent / "x.png"))], [text("好")]])
    send(env, "画")
    tool = steps(env, last_turn(env)["id"])[0]
    assert tool["status"] == "failed" and "项目目录" in tool["result"]["error"] and calls == []


def test_strip_draft_runs_without_approval_and_shows_its_sketch(env, monkeypatch):
    fake_sandbox(monkeypatch)
    (env.project_dir / "output" / "scripts" / "story.md").write_text(
        "# 剧本\n\n## 画面总则\n- 清淡配色\n\n## 第1条｜出门\n- 情节点：出门\n", encoding="utf-8")
    draft = "# 第1条 分镜草稿\n\n## 构思\n- 一句话：出门\n\n## 版式\n- 共1格：整页一格\n\n## 画面指令\n### 第1格\n远景，门口。\n\n```python\npass\n```"
    fake = use_llm(monkeypatch, [
        [call("draft_strip", "s1", script_path="output/scripts/story.md", strip_index=1, character_names=["小樱"])],
        [text(draft)],  # 起草（工具里单独调用的模型）
        [text(draft)],  # 编辑检查
        [text("草稿好了")],
    ])
    send(env, "写第一条的分镜草稿")  # 生成前确认模式下也直接执行
    turn = last_turn(env)
    assert turn["status"] == "completed"
    tool = steps(env, turn["id"])[0]
    sketch = env.project_dir / "output" / "layouts" / "strip_1.png"
    assert tool["status"] == "completed" and tool["result"]["panels"] == 1 and tool["result"]["summary"] == "出门"
    assert tool["display"]["media"][0]["path"] == str(sketch)
    assert (env.project_dir / "output" / "scripts" / "strips" / "strip_1.md").is_file()

    # 起草的两次请求不带工具、不用主对话的历史；主对话下一次请求附上草图，草稿全文不进主对话的历史
    assert [bool(r["tools"]) for r in fake.requests] == [True, False, False, True]
    assert len(fake.requests[1]["messages"]) == 1
    assert [p["type"] for p in fake.requests[3]["messages"][-1]["parts"]] == ["function_response", "text", "image"]
    assert "远景，门口" not in json.dumps(env.db.get_history(env.id), ensure_ascii=False)


def test_comic_strip_follows_the_layout_sketch(env, monkeypatch):
    captured: dict = {}

    def generate(prompt, refs, **kwargs):
        captured.update(prompt=prompt, refs=list(refs))
        return image_provider.GeneratedImage(b"png", "image/png")

    monkeypatch.setattr(image_provider, "generate", generate)
    character = env.project_dir / "output" / "stylized" / "a.png"
    character.write_bytes(b"png")
    layout = env.project_dir / "output" / "layouts" / "strip_1.png"
    layout.parent.mkdir(parents=True)
    layout.write_bytes(b"png")
    ctx = base.ToolContext(project_dir=env.project_dir)
    args = {"character_paths": ["output/stylized/a.png"], "character_names": ["小樱"], "script": "1 远景", "strip_index": 1,
            "output_path": "output/panels/strip_1.png", "layout_path": "output/layouts/strip_1.png"}
    tool = base.get("generate_comic_strip")

    assert base.execute(tool, args, ctx)["output_path"] == str(env.project_dir / "output" / "panels" / "strip_1.png")
    assert captured["refs"] == [str(character), str(layout)]  # 草图是最后一张参考图
    prompt = captured["prompt"]
    assert "Image 2: PANEL LAYOUT SKETCH" in prompt and "follow Image 2 exactly" in prompt and "Do NOT draw the numbers" in prompt
    assert "with 4-6 panels" not in prompt

    # 没有草图时和原来一样
    base.execute(tool, {**args, "layout_path": ""}, ctx)
    assert captured["refs"] == [str(character)]
    assert "PANEL LAYOUT" not in captured["prompt"] and "with 4-6 panels" in captured["prompt"]
    assert base.execute(tool, {**args, "layout_path": "output/layouts/missing.png"}, ctx)["error"].startswith("版式草图不存在")


# ---- 工具声明 / 分镜模式休眠 ----


def test_tool_declarations_are_json_schema():
    tools = {t.name: t.schema for t in base.for_mode("storyboard")}
    params = tools["select_characters"]["parameters"]
    assert params["type"] == "object" and params["required"] == ["preselected"]
    assert params["properties"]["preselected"]["items"]["properties"]["path"]["type"] == "string"
    assert tools["select_faces"]["parameters"] == {"type": "object", "properties": {}}
    assert "video_mode" not in tools["generate_video_clip"]["parameters"]["properties"]


STORYBOARD_ONLY = {"generate_storyboard_strip", "generate_video_clip", "merge_video_clips", "write_storyboard", "read_storyboard"}


def test_storyboard_mode_is_dormant_by_default(env, monkeypatch):
    (env.project_dir / "output" / "panels" / "strip_1.png").write_bytes(b"png")
    (env.project_dir / "output" / "videos").mkdir()
    (env.project_dir / "output" / "videos" / "clip_1.mp4").write_bytes(b"mp4")
    fake = use_llm(monkeypatch, [[text("好")]])
    env.cancel_event.clear()
    with env.run_lock:
        list(env.send(new_id(), {"text": "做个分镜", "attachments": []}, lang="zh", mode="storyboard", interaction="auto"))
    request = fake.requests[0]
    assert not set(request["tools"]) & STORYBOARD_ONLY and "generate_comic_strip" in request["tools"]
    system = request["system"].replace(str(env.project_dir), "")  # 临时目录名里带测试名
    # 条漫的「分镜草稿」不算；分镜模式自己的说法都不能出现
    assert not any(word in system for word in ("分镜模式", "分镜脚本", "分镜视频", "首帧", "video", "storyboard"))
    assert "strip_1.png" in system and "clip_1.mp4" not in system


def test_storyboard_mode_can_be_reenabled(env, monkeypatch):
    monkeypatch.setattr(features, "STORYBOARD", True)
    fake = use_llm(monkeypatch, [[text("好")]])
    env.cancel_event.clear()
    with env.run_lock:
        list(env.send(new_id(), {"text": "做个分镜", "attachments": []}, lang="zh", mode="storyboard", interaction="auto"))
    assert STORYBOARD_ONLY <= set(fake.requests[0]["tools"])
    assert "分镜" in fake.requests[0]["system"]
