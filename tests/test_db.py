"""Tests for ConversationDB (SQLite persistence layer)."""

import json
import sqlite3
from pathlib import Path

import pytest

from src.web.db import ConversationDB, conversation_turns


@pytest.fixture()
def db(tmp_path: Path) -> ConversationDB:
    """Create a fresh in-tmp-dir database for each test."""
    db = ConversationDB(tmp_path / "test.db")
    yield db
    db.close()


def text_entry(text: str, role: str = "user") -> dict:
    return {"role": role, "parts": [{"type": "text", "text": text}]}


# ---- Conversations ----


class TestConversations:
    def test_create_and_list(self, db: ConversationDB) -> None:
        cid = db.create_conversation("demo", "en")
        convs = db.list_conversations("demo")
        assert [(c["id"], c["project"], c["lang"], c["message_count"]) for c in convs] == [(cid, "demo", "en", 0)]

    def test_list_filters_by_project(self, db: ConversationDB) -> None:
        db.create_conversation("alpha")
        db.create_conversation("beta")
        assert len(db.list_conversations("alpha")) == 1
        assert len(db.list_conversations("gamma")) == 0

    def test_message_count_counts_turns(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj")
        db.create_turn(cid, "t1", {"text": "a", "attachments": []})
        db.create_turn(cid, "t2", {"text": "b", "attachments": []})
        assert db.list_conversations("proj")[0]["message_count"] == 2

    def test_delete_conversation_cascades(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj")
        db.append_history(cid, 0, text_entry("hi"), "t1")
        db.create_turn(cid, "t1", {"text": "hi", "attachments": []})
        step = db.create_step("t1", "message", "completed", text="好")
        db.create_job("job_1", cid, "t1", step["id"], "generate_asset", {})

        db.delete_conversation(cid)
        assert db.list_conversations("proj") == []
        assert db.get_history(cid) == []
        assert db.get_turn("t1") is None and db.get_step(step["id"]) is None and db.get_job("job_1") is None

    def test_update_conversation(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj", lang="zh")
        db.update_conversation(cid, title="My Comic", lang="en", unknown_field="ignored")
        conv = db.get_conversation(cid)
        assert (conv["title"], conv["lang"]) == ("My Comic", "en")


# ---- History ----


class TestHistory:
    def test_append_and_get_ordered_by_seq(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj")
        db.append_history(cid, 1, text_entry("hi there", "model"))
        db.append_history(cid, 0, text_entry("hello"))
        assert db.get_history(cid) == [text_entry("hello"), text_entry("hi there", "model")]

    def test_append_same_seq_overwrites(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj")
        db.append_history(cid, 0, text_entry("a"))
        db.append_history(cid, 0, text_entry("b"))
        assert db.get_history(cid) == [text_entry("b")]

    def test_append_history_updates_conversation_timestamp(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj")
        before = db.get_conversation(cid)["updated_at"]
        db.append_history(cid, 0, text_entry("x"))
        assert db.get_conversation(cid)["updated_at"] >= before


# ---- Turns / steps / jobs ----


class TestTurns:
    def test_turns_are_numbered_per_conversation(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj")
        other = db.create_conversation("proj")
        first = db.create_turn(cid, "a", {"text": "1", "attachments": []})
        second = db.create_turn(cid, "b", {"text": "2", "attachments": []})
        elsewhere = db.create_turn(other, "c", {"text": "x", "attachments": []})
        assert (first["seq"], second["seq"], elsewhere["seq"]) == (0, 1, 0)
        assert first["status"] == "running" and first["input"]["text"] == "1" and first["legacy"] is False
        assert db.last_turn(cid)["id"] == "b"
        assert [t["id"] for t in db.list_turns(cid)] == ["a", "b"]

    def test_update_turn(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj")
        db.create_turn(cid, "a", {"text": "1", "attachments": []})
        turn = db.update_turn("a", status="failed", error="坏了", error_kind="config")
        assert (turn["status"], turn["error"], turn["error_kind"]) == ("failed", "坏了", "config")
        with pytest.raises(ValueError):
            db.update_turn("a", conversation_id="other")

    def test_delete_turns_from_rewinds_history_steps_and_jobs(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj")
        db.append_history(cid, 0, text_entry("旧版对话的历史"))  # turn_id 为空：一直保留
        for i, turn_id in enumerate(["t0", "t1", "t2"]):
            db.create_turn(cid, turn_id, {"text": str(i), "attachments": []})
            db.append_history(cid, i + 1, text_entry(str(i)), turn_id)
            step = db.create_step(turn_id, "tool", "completed", tool="generate_asset")
            db.create_job(f"job_{i}", cid, turn_id, step["id"], "generate_asset", {})

        assert db.delete_turns_from(cid, 1) == ["t1", "t2"]
        assert [h["parts"][0]["text"] for h in db.get_history(cid)] == ["旧版对话的历史", "0"]
        assert [t["id"] for t in db.list_turns(cid)] == ["t0"]
        assert [j["id"] for j in db.list_jobs(cid)] == ["job_0"]
        # 之后的新 turn 和历史接着编号
        assert db.create_turn(cid, "t3", {"text": "3", "attachments": []})["seq"] == 1

    def test_steps_keep_json_fields_and_order(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj")
        db.create_turn(cid, "t", {"text": "", "attachments": []})
        first = db.create_step("t", "tool", "running", tool="list_files", call_id="c1", args={"directory": "/x"})
        second = db.create_step("t", "message", "running", text="")
        assert (first["seq"], second["seq"]) == (0, 1)
        updated = db.update_step(first["id"], status="completed", result={"files": ["a"]}, display={"media": []}, duration_ms=12)
        assert updated["args"] == {"directory": "/x"} and updated["result"] == {"files": ["a"]}
        assert updated["display"] == {"media": []} and updated["duration_ms"] == 12 and updated["call_id"] == "c1"
        assert [s["id"] for s in db.steps_for_turn("t")] == [first["id"], second["id"]]
        with pytest.raises(ValueError):
            db.update_step(first["id"], tool="other")

    def test_jobs_queries(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj")
        for job_id, turn_id in [("j1", "t1"), ("j2", "t1"), ("j3", "t2")]:
            db.create_job(job_id, cid, turn_id, None, "generate_asset", {"prompt": job_id})
        db.update_job("j1", status="succeeded", result={"output_path": "/a.png"}, media=[{"path": "/a.png"}])
        assert [j["id"] for j in db.list_jobs(cid, ids=["j3", "j1"])] == ["j1", "j3"]
        assert [j["id"] for j in db.list_jobs(cid, unfinished=True)] == ["j2", "j3"]
        # 这一轮的任务 + 所有还没结束的任务
        assert [j["id"] for j in db.list_jobs(cid, turn_id="t1", unfinished=True)] == ["j1", "j2", "j3"]
        assert db.get_job("j1")["media"] == [{"path": "/a.png"}] and db.get_job("j2")["args"] == {"prompt": "j2"}
        assert db.fail_unfinished_jobs("服务重启") == 2
        assert {j["status"] for j in db.list_jobs(cid)} == {"succeeded", "failed"}

    def test_interrupted_turns_are_cancelled_on_startup(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj")
        db.create_turn(cid, "running", {"text": "", "attachments": []})
        tool = db.create_step("running", "tool", "running", tool="list_files")
        message = db.create_step("running", "message", "running", text="说到一半")
        db.create_turn(cid, "waiting", {"text": "", "attachments": []})
        db.update_turn("waiting", status="awaiting_approval")

        db.interrupt_running_turns("服务重启")
        assert db.get_turn("running")["status"] == "cancelled"
        assert db.get_turn("waiting")["status"] == "awaiting_approval"
        assert db.get_step(tool["id"])["status"] == "cancelled" and db.get_step(tool["id"])["result"] == {"error": "服务重启"}
        assert db.get_step(message["id"])["status"] == "completed"

    def test_conversation_turns_view_includes_jobs(self, db: ConversationDB) -> None:
        cid = db.create_conversation("proj")
        db.create_turn(cid, "t", {"text": "画", "attachments": []})
        step = db.create_step("t", "tool", "completed", tool="generate_asset", args={"prompt": "猫"}, job_id="job_x")
        db.create_job("job_x", cid, "t", step["id"], "generate_asset", {"prompt": "猫"})
        db.create_step("t", "message", "completed", text="好了")
        [turn] = conversation_turns(db, cid)
        tool_view, message_view = turn["steps"]
        assert turn["input"]["text"] == "画"
        assert tool_view["tool"] == "generate_asset" and tool_view["job"]["status"] == "queued"
        assert message_view == {**message_view, "kind": "message", "text": "好了"}


# ---- Migration from older databases ----


def _old_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE conversations (id TEXT PRIMARY KEY, project TEXT NOT NULL, lang TEXT DEFAULT 'zh',
            title TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE history_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
            seq INTEGER NOT NULL, content_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE ui_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
            turn_id TEXT, role TEXT, content TEXT DEFAULT '', tool_calls_json TEXT, images_json TEXT,
            attached_images_json TEXT, message_type TEXT, created_at TEXT NOT NULL);
        INSERT INTO conversations VALUES ('c', 'p', 'zh', '', 'x', 'x');
        INSERT INTO history_entries (conversation_id, seq, content_json, created_at) VALUES
            ('c', 0, '{"role": "user", "parts": []}', 'x'),
            ('c', 1, '{"role": "model", "parts": []}', 'x'),
            ('c', 1, '{"role": "model", "parts": []}', 'x'),
            ('c', 2, '{"role": "user", "parts": []}', 'x');
        """
    )
    rows = [
        ("u1", "user", "", None, None, json.dumps([{"path": "/p/input/a.png", "url": "/files/projects/p/input/a.png", "name": "a.png", "previewUrl": "blob:x"}]), "image"),
        ("u1", "user", "看看这张图", None, None, None, "text"),
        ("a1", "assistant", "检测到一张人脸", json.dumps([
            {"tool": "detect_faces_in_image", "args": {"image_path": "/p/input/a.png"}, "result": {"count": 1},
             "images": [{"path": "/p/output/faces/f.png", "url": "/files/projects/p/output/faces/f.png", "tool": "detect_faces_in_image"}],
             "duration_ms": 900},
            {"tool": "propose_plan", "args": {}, "result": {"type": "task_plan", "steps": [{"id": 1, "label": "风格化"}]}},
        ]), None, None, None),
        ("u2", "user", "已选择角色", None, None, None, "text"),
        ("a2", "assistant", "", json.dumps([
            {"tool": "generate_comic_strip", "args": {"strip_index": 1}, "result": {"error": "额度不足"}},
            {"tool": "generate_asset", "args": {}, "result": {"output_path": "/p/output/x.png"}, "verdict": "accepted"},
        ]), None, None, None),
    ]
    conn.executemany(
        "INSERT INTO ui_messages (conversation_id, turn_id, role, content, tool_calls_json, images_json, attached_images_json, message_type, created_at) "
        "VALUES ('c', ?, ?, ?, ?, ?, ?, ?, 'x')",
        rows,
    )
    conn.commit()
    conn.close()


def test_old_database_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    _old_database(path)
    migrated = ConversationDB(path)

    # 旧版本并发时写出的重复历史去掉了；旧历史整段保留（不属于任何 turn）
    assert [h["role"] for h in migrated.get_history("c")] == ["user", "model", "user"]
    turns = conversation_turns(migrated, "c")
    assert [t["legacy"] for t in turns] == [True, True]

    first, second = turns
    assert first["input"]["text"] == "看看这张图"
    assert first["input"]["attachments"] == [{"path": "/p/input/a.png", "url": "/files/projects/p/input/a.png", "name": "a.png"}]
    faces, plan, message = first["steps"]
    assert faces["tool"] == "detect_faces_in_image" and faces["display"]["media"][0]["path"] == "/p/output/faces/f.png"
    assert plan["display"]["plan"] == {"status": "expired", "steps": [{"id": 1, "label": "风格化"}]}
    assert message["text"] == "检测到一张人脸"

    failed, kept = second["steps"]
    assert failed["status"] == "failed" and kept["verdict"] == "accepted"
    migrated.close()

    # 再次打开不会重复转换
    again = ConversationDB(path)
    assert len(again.list_turns("c")) == 2
    again.close()


def test_legacy_context_titles_are_cleaned(tmp_path: Path) -> None:
    path = tmp_path / "titles.db"
    first = ConversationDB(path)
    cid = first.create_conversation("p")
    first.update_conversation(cid, title="[以下是之前的对话记录，请基于此上下文继续]\n用户: 我们那个县城归安徽管")
    other = first.create_conversation("p")
    first.update_conversation(other, title="正常标题")
    first.close()

    reopened = ConversationDB(path)
    titles = {c["id"]: c["title"] for c in reopened.list_conversations("p")}
    assert titles == {cid: "我们那个县城归安徽管", other: "正常标题"}
    reopened.close()


# ---- Projects ----


class TestProjects:
    def test_rename_moves_conversations_and_rewrites_paths(self, db: ConversationDB) -> None:
        cid = db.create_conversation("old")
        other = db.create_conversation("older")
        entry = {"role": "user", "parts": [{"type": "image", "path": "/root/projects/old/input/a.png"}]}
        db.append_history(cid, 0, entry, "t")
        db.append_history(other, 0, entry)
        db.create_turn(cid, "t", {"text": "", "attachments": [{"path": "/root/projects/old/input/a.png", "url": "/files/projects/old/input/a.png"}]})
        step = db.create_step("t", "tool", "completed", tool="generate_asset", args={"output_path": "/root/projects/old/output/a.png"},
                              display={"media": [{"url": "/files/projects/old/output/a.png?v=1"}]})
        db.create_step("t", "message", "completed", text="![x](/files/projects/old/output/a.png)")
        db.create_job("job_r", cid, "t", step["id"], "generate_asset", {"output_path": "/root/projects/old/output/a.png"})

        db.rename_project("old", "new", [
            ("/root/projects/old/", "/root/projects/new/"),
            ("/files/projects/old/", "/files/projects/new/"),
        ])
        assert [c["id"] for c in db.list_conversations("new")] == [cid]
        assert db.get_history(cid)[0]["parts"][0]["path"] == "/root/projects/new/input/a.png"
        [turn] = conversation_turns(db, cid)
        assert turn["input"]["attachments"][0] == {"path": "/root/projects/new/input/a.png", "url": "/files/projects/new/input/a.png"}
        tool_step, message_step = turn["steps"]
        assert tool_step["args"]["output_path"] == "/root/projects/new/output/a.png"
        assert tool_step["display"]["media"][0]["url"] == "/files/projects/new/output/a.png?v=1"
        assert message_step["text"] == "![x](/files/projects/new/output/a.png)"
        assert db.get_job("job_r")["args"]["output_path"] == "/root/projects/new/output/a.png"
        # 其他项目（名字是前缀）不受影响
        assert db.get_history(other)[0]["parts"][0]["path"] == "/root/projects/old/input/a.png"

    def test_delete_project_removes_conversations(self, db: ConversationDB) -> None:
        cid = db.create_conversation("gone")
        db.append_history(cid, 0, {"role": "user", "parts": []})
        db.create_conversation("kept")
        db.delete_project("gone")
        assert db.list_conversations("gone") == []
        assert db.get_history(cid) == []
        assert len(db.list_conversations("kept")) == 1
