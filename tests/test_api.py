"""HTTP 接口：项目名校验、素材路径越界、对话的每一轮（发送 / 批准 / 重试 / 删除）、项目改名 / 删除时的对话记录（离线，假 LLM）。"""

import dataclasses
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.providers import llm
from src.providers import settings as provider_settings
from src.web import api
from src.web.agent import JobManager, Sessions
from src.web.agent.tools import base
from src.web.db import ConversationDB


@pytest.fixture
def client(monkeypatch, tmp_path):
    root = tmp_path / "root"
    projects = root / "projects"
    projects.mkdir(parents=True)
    test_db = ConversationDB(tmp_path / "test.db")
    jobs = JobManager(test_db)
    monkeypatch.setattr(api, "PROJECT_ROOT", root)
    monkeypatch.setattr(api, "PROJECTS_DIR", projects)
    monkeypatch.setattr(api, "db", test_db)
    monkeypatch.setattr(api, "jobs", jobs)
    monkeypatch.setattr(api, "sessions", Sessions(test_db, jobs, projects))
    monkeypatch.setattr(base, "PROJECT_ROOT", root)
    monkeypatch.setattr(provider_settings, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(provider_settings, "ENV_PATH", tmp_path / ".env")
    yield TestClient(api.app)
    test_db.close()


class ScriptedLLM:
    """按顺序返回预设回复；没有预设时回复「好的」。"""

    def __init__(self):
        self.replies: list[list[dict]] = []
        self.requests: list[list[dict]] = []

    def __call__(self, role, system, messages, tools=None, **kwargs):
        self.requests.append([dict(m) for m in messages])
        parts = self.replies.pop(0) if self.replies else [{"type": "text", "text": "好的"}]
        for part in parts:
            if part["type"] == "text":
                yield {"type": "text", "text": part["text"]}
        yield {"type": "message", "message": {"role": "model", "parts": parts}}


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setattr(provider_settings, "resolve", lambda role, model=None: None)
    monkeypatch.setattr(provider_settings, "concurrency", lambda role: 2)
    scripted = ScriptedLLM()
    monkeypatch.setattr(llm, "stream_chat", scripted)
    return scripted


def sse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def chat(client, text: str, **fields) -> tuple[str, list[tuple[str, dict]]]:
    events = sse_events(client.post("/api/chat", json={"text": text, "project": "p", **fields}).text)
    return events[0][1]["conversation_id"], events


def turns_of(client, cid: str) -> list[dict]:
    return client.get(f"/api/conversations/{cid}/turns").json()


def test_project_names_are_validated(client):
    for bad in ["..", ".", "a/b", ".hidden", "  "]:
        assert client.post("/api/projects", json={"name": bad}).status_code == 400
    assert client.get("/api/assets", params={"project": ".."}).status_code == 400
    assert client.delete("/api/projects/..").status_code in (400, 404)
    res = client.post("/api/projects", json={"name": " 我的项目 "}).json()
    assert res == {"name": "我的项目", "created": True}
    info = client.get("/api/projects").json()
    assert info[0]["name"] == "我的项目" and info[0]["image_count"] == 0 and info[0]["cover"] is None


def test_asset_paths_cannot_escape_projects(client):
    client.post("/api/projects", json={"name": "p"})
    secret = api.PROJECT_ROOT / "settings.json"
    secret.write_text("{}", encoding="utf-8")
    sneaky = str(api.PROJECTS_DIR / "p" / ".." / ".." / "settings.json")
    assert client.request("DELETE", "/api/assets", json={"path": sneaky}).status_code == 403
    assert client.put("/api/assets", json={"path": sneaky.replace("settings.json", "README.md"), "content": "x"}).status_code == 403
    assert secret.exists()


def test_delete_asset_removes_metadata(client):
    client.post("/api/projects", json={"name": "p"})
    folder = api.PROJECTS_DIR / "p" / "output" / "stylized"
    (folder / "a.png").write_bytes(b"png")
    (folder / "assets.json").write_text(json.dumps({"a.png": {"name": "a"}, "b.png": {"name": "b"}}), encoding="utf-8")
    assert client.request("DELETE", "/api/assets", json={"path": str(folder / "a.png")}).json() == {"deleted": True}
    assert json.loads((folder / "assets.json").read_text(encoding="utf-8")) == {"b.png": {"name": "b"}}


def test_strip_drafts_and_layout_sketches_are_listed(client):
    client.post("/api/projects", json={"name": "p"})
    output = api.PROJECTS_DIR / "p" / "output"
    (output / "scripts" / "story.md").write_text("# 总剧本", encoding="utf-8")
    (output / "scripts" / "strips" / "strip_1.md").write_text("# 第1条 分镜草稿", encoding="utf-8")
    (output / "layouts" / "strip_1.png").write_bytes(b"png")
    (output / "layouts" / "strip_1.py").write_text("pass", encoding="utf-8")
    assets = client.get("/api/assets", params={"project": "p"}).json()
    assert [a["name"] for a in assets["scripts"]] == ["story.md"]  # 草稿在子目录里，不混进剧本
    assert [(a["name"], a["type"], a["content"]) for a in assets["drafts"]] == [("strip_1.md", "markdown", "# 第1条 分镜草稿")]
    assert [a["name"] for a in assets["layouts"]] == ["strip_1.png"]  # 画图代码不列出来


def test_skills_are_listed_with_project_overrides(client):
    client.post("/api/projects", json={"name": "p"})
    skill = api.PROJECTS_DIR / "p" / "skills" / "strip-draft"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: 我的分镜写法\ndescription: 项目自己的\n---\n\n# 写法", encoding="utf-8")
    items = {a["name"]: a for a in client.get("/api/assets", params={"project": "p"}).json()["skills"]}
    assert "storyboard-video" not in items  # 分镜模式休眠：不列分镜的技能
    builtin = items["master-script"]
    assert builtin["readonly"] is True and builtin["url"] == "" and builtin["content"].startswith("---\nname: 总剧本")
    own = items["strip-draft"]
    assert own["source"] == "project" and "readonly" not in own and own["title"] == "我的分镜写法"
    assert own["url"].startswith("/files/projects/p/skills/strip-draft/SKILL.md")
    # 项目技能可以在界面里改，内置的不行（不在 projects/ 里）
    assert client.put("/api/assets", json={"path": own["path"], "content": own["content"] + "\n- 新规则"}).json()["updated"]
    assert client.put("/api/assets", json={"path": builtin["path"], "content": "x"}).status_code == 403


def test_upload_only_accepts_images(client):
    client.post("/api/projects", json={"name": "p"})
    res = client.post("/api/upload", params={"project": "p"}, files={"file": ("x.exe", b"MZ")})
    assert res.status_code == 400
    res = client.post("/api/upload", params={"project": "p"}, files={"file": ("photo.PNG", b"\x89PNG")}).json()
    assert res["name"].endswith(".png") and res["url"].startswith("/files/projects/p/input/")


def test_chat_creates_conversation_and_turns(client, fake_llm):
    client.post("/api/projects", json={"name": "p"})
    cid, events = chat(client, "第一句", turn_id="turn-0001", title="第一句")
    assert [e for e, _ in events] == ["conversation", "turn", "step", "delta", "step", "turn", "done"]
    assert events[1][1]["turn"]["id"] == "turn-0001"
    chat(client, "第二句", conversation_id=cid, turn_id="turn-0002")

    turns = turns_of(client, cid)
    assert [(t["id"], t["status"], t["input"]["text"]) for t in turns] == [("turn-0001", "completed", "第一句"), ("turn-0002", "completed", "第二句")]
    assert turns[0]["steps"][0]["text"] == "好的"
    assert api.db.list_conversations("p")[0]["title"] == "第一句"
    assert len(api.db.get_history(cid)) == 4

    # 服务重启后（内存里没有运行时）也能接着同一个对话
    api.sessions._items.clear()
    assert chat(client, "第三句", conversation_id=cid)[0] == cid
    assert len(api.db.list_conversations("p")) == 1
    assert client.post("/api/chat", json={"text": "x", "conversation_id": "nope"}).status_code == 404


def test_retry_edit_and_delete_rewind_the_conversation(client, fake_llm):
    client.post("/api/projects", json={"name": "p"})
    cid, _ = chat(client, "第一句", turn_id="turn-0001")
    chat(client, "第二句", conversation_id=cid, turn_id="turn-0002")
    chat(client, "第三句", conversation_id=cid, turn_id="turn-0003")

    # 编辑第二句：第二、三轮被替换
    events = sse_events(client.post("/api/turns/turn-0002/retry", json={"text": "改过的第二句", "turn_id": "turn-0004"}).text)
    assert events[0][1]["turn"]["id"] == "turn-0004"
    assert [t["input"]["text"] for t in turns_of(client, cid)] == ["第一句", "改过的第二句"]
    assert len(api.db.get_history(cid)) == 4
    assert fake_llm.requests[-1][-1]["parts"][-1]["text"] == "改过的第二句"

    # 原样重试第一句
    client.post("/api/turns/turn-0001/retry", json={})
    assert [t["input"]["text"] for t in turns_of(client, cid)] == ["第一句"]

    # 删除唯一的一轮：历史清空
    first = turns_of(client, cid)[0]["id"]
    assert client.delete(f"/api/turns/{first}").json() == {"deleted": [first]}
    assert turns_of(client, cid) == [] and api.db.get_history(cid) == []
    assert client.delete("/api/turns/nope").status_code == 404


def test_approval_flow_over_http(client, fake_llm, monkeypatch):
    client.post("/api/projects", json={"name": "p"})

    def generate(args, ctx):
        out = Path(args["output_path"])
        out.write_bytes(b"png")
        return {"output_path": str(out)}

    monkeypatch.setitem(base._TOOLS, "generate_asset", dataclasses.replace(base._TOOLS["generate_asset"], run=generate))
    fake_llm.replies = [
        [{"type": "function_call", "id": "g1", "name": "generate_asset", "args": {"prompt": "猫", "output_path": "output/stylized/cat.png"}}],
        [{"type": "function_call", "id": "k1", "name": "check_jobs", "args": {"wait_seconds": 5}}],
        [{"type": "text", "text": "画好了"}],
    ]
    cid, events = chat(client, "画一只猫", interaction_mode="confirm")
    turn = turns_of(client, cid)[0]
    assert turn["status"] == "awaiting_approval"
    step = turn["steps"][0]
    assert step["status"] == "pending_approval" and step["tool"] == "generate_asset"

    events = sse_events(client.post(f"/api/turns/{turn['id']}/resume", json={"responses": {step["id"]: {"approve": True}}}).text)
    assert ("done", {"event": "done"}) in events
    assert any(e == "job" for e, _ in events)
    turn = turns_of(client, cid)[0]
    generate_step, check_step, message = turn["steps"]
    assert turn["status"] == "completed" and message["text"] == "画好了"
    assert generate_step["job"]["status"] == "succeeded"
    assert generate_step["job"]["media"][0]["url"].startswith("/files/projects/p/output/stylized/cat.png")

    # 不在等待中的 turn 不能再 resume
    events = sse_events(client.post(f"/api/turns/{turn['id']}/resume", json={"responses": {}}).text)
    assert events[0][0] == "error"

    # 记录对生成结果的处理；后台任务可以单独查询
    assert client.patch(f"/api/steps/{generate_step['id']}", json={"verdict": "accepted"}).json()["verdict"] == "accepted"
    assert client.patch(f"/api/steps/{generate_step['id']}", json={"verdict": "maybe"}).status_code == 400
    jobs = client.get(f"/api/conversations/{cid}/jobs", params={"ids": generate_step["job"]["id"]}).json()
    assert [j["status"] for j in jobs] == ["succeeded"]
    assert client.get(f"/api/conversations/{cid}/jobs", params={"active": True}).json() == []


def test_stop_settles_a_turn_waiting_for_approval(client, fake_llm):
    client.post("/api/projects", json={"name": "p"})
    fake_llm.replies = [[{"type": "function_call", "id": "g1", "name": "generate_asset", "args": {"prompt": "猫", "output_path": "output/a.png"}}]]
    cid, _ = chat(client, "画", interaction_mode="confirm")
    assert client.post("/api/chat/stop", json={"conversation_id": cid}).json() == {"stopping": False}
    turn = turns_of(client, cid)[0]
    assert turn["status"] == "cancelled" and turn["steps"][0]["status"] == "cancelled"
    assert client.post("/api/chat/stop", json={"conversation_id": "nope"}).json() == {"stopping": False}


def test_legacy_turns_are_read_only(client, fake_llm):
    cid = api.db.create_conversation("p")
    api.db.conn.execute(
        "INSERT INTO turns (id, conversation_id, seq, status, input_json, legacy, created_at, updated_at) "
        "VALUES ('old-turn-1', ?, 0, 'completed', '{\"text\": \"旧消息\", \"attachments\": []}', 1, 'x', 'x')",
        (cid,),
    )
    api.db.conn.commit()
    assert client.post("/api/turns/old-turn-1/retry", json={}).status_code == 400
    assert client.delete("/api/turns/old-turn-1").status_code == 400
    # 旧对话可以接着聊
    assert chat(client, "继续", conversation_id=cid)[0] == cid
    assert [t["legacy"] for t in turns_of(client, cid)] == [True, False]


def test_rename_and_delete_project_keep_conversations_consistent(client, fake_llm):
    client.post("/api/projects", json={"name": "old"})
    cid = sse_events(client.post("/api/chat", json={"text": "hi", "project": "old"}).text)[0][1]["conversation_id"]

    assert client.put("/api/projects/old", json={"new_name": "new"}).json()["renamed"] is True
    assert [c["id"] for c in client.get("/api/conversations", params={"project": "new"}).json()] == [cid]
    assert cid not in api.sessions._items  # 旧路径的运行时已丢弃，下次按新路径重建

    assert client.delete("/api/projects/new").json() == {"deleted": True}
    assert client.get("/api/conversations", params={"project": "new"}).json() == []


def test_conversation_title_and_delete(client, fake_llm):
    cid = api.db.create_conversation("p")
    assert client.put(f"/api/conversations/{cid}", json={"title": " 新标题 "}).json() == {"updated": True}
    assert api.db.list_conversations("p")[0]["title"] == "新标题"
    assert client.put("/api/conversations/nope", json={"title": "x"}).status_code == 404
    assert client.delete(f"/api/conversations/{cid}").json() == {"deleted": True}
    assert client.get(f"/api/conversations/{cid}/turns").status_code == 404


def test_storyboard_is_dormant(client, fake_llm):
    assert client.get("/api/settings").json()["features"] == {"storyboard": False}
    client.post("/api/projects", json={"name": "demo"})
    output = api.PROJECTS_DIR / "demo" / "output"
    assert (output / "panels").is_dir()
    assert not (output / "videos").exists() and not (output / "storyboards").exists()


def test_startup_marks_interrupted_work(client):
    cid = api.db.create_conversation("p")
    api.db.create_turn(cid, "turn-running", {"text": "", "attachments": []})
    api.db.create_job("job_old", cid, "turn-running", None, "generate_asset", {})
    # 只是导入 / 使用接口不会动正在运行的实例；服务启动时才清理上次中断的任务
    assert api.db.get_turn("turn-running")["status"] == "running"
    with TestClient(api.app):
        pass
    assert api.db.get_turn("turn-running")["status"] == "cancelled"
    assert api.db.get_job("job_old")["status"] == "failed"
