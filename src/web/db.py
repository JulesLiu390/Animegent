"""SQLite 持久化：对话（Session）→ Turn（用户一次输入）→ Step（模型的一段文字或一次工具调用），
外加给模型看的历史（history_entries，按 turn 归属）和后台生成任务（jobs）。

所有数据都由后端写入，前端只读：刷新、断线、服务重启都不会丢状态。
"""

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.web.legacy import convert_ui_messages


def utc_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


_LEGACY_CONTEXT_PREFIX = "[以下是之前的对话记录"


def _clean_legacy_title(title: str) -> str:
    """旧版重试 / 编辑时会把隐藏的上下文写进标题：取出其中第一句用户消息。"""
    match = re.search(r"用户: (?:\[\d+张图片\] )?(.+)", title)
    return match.group(1).strip()[:60] if match else ""


def _dumps(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _loads(raw: str | None) -> Any:
    return json.loads(raw) if raw else None


TURN_ACTIVE = ("running", "awaiting_approval", "awaiting_input")
STEP_PENDING = ("pending_approval", "awaiting_input")
JOB_UNFINISHED = ("queued", "running")

_JSON_COLUMNS = {
    "turns": {"input_json"},
    "steps": {"args_json", "result_json", "display_json"},
    "jobs": {"args_json", "result_json", "media_json"},
}
_UPDATABLE = {
    "turns": {"status", "error", "error_kind", "input_json"},
    "steps": {"status", "result_json", "display_json", "text", "verdict", "job_id", "started_at", "finished_at", "duration_ms"},
    "jobs": {"status", "result_json", "media_json", "error", "started_at", "finished_at"},
}


class ConversationDB:
    """Manages conversations, turns, steps, model history and background jobs in SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # 同一个连接会被请求线程、Agent 工作线程和后台任务线程同时使用
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id          TEXT PRIMARY KEY,
                    project     TEXT NOT NULL,
                    lang        TEXT DEFAULT 'zh',
                    title       TEXT DEFAULT '',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );

                -- 给模型看的历史（格式见 src/providers/llm.py）；turn_id 为空的是旧版对话留下的历史
                CREATE TABLE IF NOT EXISTS history_entries (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    seq             INTEGER NOT NULL,
                    content_json    TEXT NOT NULL,
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS turns (
                    id              TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    seq             INTEGER NOT NULL,
                    status          TEXT NOT NULL,
                    input_json      TEXT NOT NULL,
                    error           TEXT,
                    error_kind      TEXT,
                    legacy          INTEGER NOT NULL DEFAULT 0,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS steps (
                    id              TEXT PRIMARY KEY,
                    turn_id         TEXT NOT NULL,
                    seq             INTEGER NOT NULL,
                    kind            TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    tool            TEXT,
                    call_id         TEXT,
                    args_json       TEXT,
                    result_json     TEXT,
                    display_json    TEXT,
                    text            TEXT,
                    verdict         TEXT,
                    job_id          TEXT,
                    started_at      TEXT,
                    finished_at     TEXT,
                    duration_ms     INTEGER,
                    FOREIGN KEY (turn_id) REFERENCES turns(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id              TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    turn_id         TEXT,
                    step_id         TEXT,
                    tool            TEXT NOT NULL,
                    args_json       TEXT,
                    status          TEXT NOT NULL,
                    result_json     TEXT,
                    media_json      TEXT,
                    error           TEXT,
                    created_at      TEXT NOT NULL,
                    started_at      TEXT,
                    finished_at     TEXT,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_history_conversation ON history_entries(conversation_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_turns_seq ON turns(conversation_id, seq);
                CREATE INDEX IF NOT EXISTS idx_steps_turn ON steps(turn_id, seq);
                CREATE INDEX IF NOT EXISTS idx_jobs_conversation ON jobs(conversation_id, status);
                """
            )
            # 旧版本在同一对话并发执行时会把同一条历史写两次：去重后再加唯一索引，之后的写入用 upsert
            self.conn.execute(
                "DELETE FROM history_entries WHERE id NOT IN "
                "(SELECT MIN(id) FROM history_entries GROUP BY conversation_id, seq)"
            )
            self.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_history_seq ON history_entries(conversation_id, seq)"
            )
            history_columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(history_entries)")}
            if "turn_id" not in history_columns:
                self.conn.execute("ALTER TABLE history_entries ADD COLUMN turn_id TEXT")
            for row in self.conn.execute(
                "SELECT id, title FROM conversations WHERE title LIKE ?", (_LEGACY_CONTEXT_PREFIX + "%",)
            ).fetchall():
                self.conn.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?", (_clean_legacy_title(row["title"]), row["id"])
                )
            self._migrate_ui_messages()
            self.conn.commit()

    def _migrate_ui_messages(self) -> None:
        """旧版由前端保存的界面消息（ui_messages）转成只读的 legacy turn；原表保留不再写入。"""
        tables = {r["name"] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "ui_messages" not in tables:
            return
        columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(ui_messages)")}
        extra = "extra_json" if "extra_json" in columns else "NULL AS extra_json"
        pending = self.conn.execute(
            """
            SELECT DISTINCT m.conversation_id FROM ui_messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE NOT EXISTS (SELECT 1 FROM turns t WHERE t.conversation_id = m.conversation_id)
            """
        ).fetchall()
        for (cid,) in pending:
            rows = self.conn.execute(
                f"SELECT turn_id, role, content, tool_calls_json, images_json, attached_images_json, message_type, {extra} "  # noqa: S608
                "FROM ui_messages WHERE conversation_id = ? ORDER BY id",
                (cid,),
            ).fetchall()
            messages = []
            for r in rows:
                msg: dict = _loads(r["extra_json"]) or {}
                msg.update({
                    "turnId": r["turn_id"], "role": r["role"], "content": r["content"] or "",
                    "toolCalls": _loads(r["tool_calls_json"]), "images": _loads(r["images_json"]),
                    "attachedImages": _loads(r["attached_images_json"]), "type": r["message_type"],
                })
                messages.append(msg)
            for seq, turn in enumerate(convert_ui_messages(messages)):
                turn_id = new_id()
                self.conn.execute(
                    "INSERT INTO turns (id, conversation_id, seq, status, input_json, error, error_kind, legacy, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (turn_id, cid, seq, turn["status"], _dumps(turn["input"]), turn["error"], turn["error_kind"], utc_now(), utc_now()),
                )
                for step_seq, step in enumerate(turn["steps"]):
                    self.conn.execute(
                        "INSERT INTO steps (id, turn_id, seq, kind, status, tool, args_json, result_json, display_json, text, verdict, duration_ms) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            new_id(), turn_id, step_seq, step["kind"], step["status"], step.get("tool"),
                            _dumps(step.get("args")), _dumps(step.get("result")), _dumps(step.get("display")),
                            step.get("text"), step.get("verdict"), step.get("duration_ms"),
                        ),
                    )

    # ---- Conversations ----

    def create_conversation(self, project: str, lang: str = "zh") -> str:
        """Create a new conversation and return its UUID."""
        cid = str(uuid.uuid4())
        now = utc_now()
        with self._lock:
            self.conn.execute(
                "INSERT INTO conversations (id, project, lang, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (cid, project, lang, now, now),
            )
            self.conn.commit()
        return cid

    def get_conversation(self, conversation_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT id, project, lang, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_conversations(self, project: str) -> list[dict]:
        """项目的所有对话，最近更新的在前；message_count 是对话里的轮数。"""
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT c.id, c.project, c.lang, c.title, c.created_at, c.updated_at,
                       (SELECT COUNT(*) FROM turns t WHERE t.conversation_id = c.id) AS message_count
                FROM conversations c
                WHERE c.project = ?
                ORDER BY c.updated_at DESC
                """,
                (project,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_conversation(self, conversation_id: str) -> None:
        """删除对话（历史、turn、step、后台任务一起级联删除）。"""
        with self._lock:
            self.conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            self.conn.commit()

    def update_conversation(self, conversation_id: str, **kwargs: str) -> None:
        """Update mutable fields (title, lang) on a conversation."""
        fields = {k: v for k, v in kwargs.items() if k in {"title", "lang"}}
        if not fields:
            return
        fields["updated_at"] = utc_now()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self.conn.execute(
                f"UPDATE conversations SET {set_clause} WHERE id = ?",  # noqa: S608
                [*fields.values(), conversation_id],
            )
            self.conn.commit()

    def touch_conversation(self, conversation_id: str) -> None:
        with self._lock:
            self.conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (utc_now(), conversation_id))
            self.conn.commit()

    # ---- Projects ----

    def conversation_ids(self, project: str) -> list[str]:
        with self._lock:
            rows = self.conn.execute("SELECT id FROM conversations WHERE project = ?", (project,)).fetchall()
        return [r["id"] for r in rows]

    def rename_project(self, old: str, new: str, replacements: list[tuple[str, str]]) -> None:
        """项目改名：对话归到新项目名下，历史、turn、step、后台任务里的旧路径 / URL 一并替换。"""
        # 表 → (属于这个对话的行, 要替换的文本列)
        text_columns = {
            "history_entries": ("conversation_id = ?", ["content_json"]),
            "turns": ("conversation_id = ?", ["input_json"]),
            "steps": ("turn_id IN (SELECT id FROM turns WHERE conversation_id = ?)", ["args_json", "result_json", "display_json", "text"]),
            "jobs": ("conversation_id = ?", ["args_json", "result_json", "media_json"]),
        }
        with self._lock:
            ids = self.conversation_ids(old)
            self.conn.execute("UPDATE conversations SET project = ? WHERE project = ?", (new, old))
            for cid in ids:
                for table, (scope, columns) in text_columns.items():
                    for column in columns:
                        for before, after in replacements:
                            self.conn.execute(
                                f"UPDATE {table} SET {column} = REPLACE({column}, ?, ?) "  # noqa: S608
                                f"WHERE {scope} AND {column} IS NOT NULL",
                                (before, after, cid),
                            )
            self.conn.commit()

    def delete_project(self, project: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM conversations WHERE project = ?", (project,))
            self.conn.commit()

    # ---- History (provider-neutral message dicts) ----

    def append_history(self, conversation_id: str, seq: int, content_dict: dict, turn_id: str | None = None) -> None:
        """写入第 ``seq`` 条历史（已存在则覆盖）。"""
        now = utc_now()
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO history_entries (conversation_id, seq, content_json, created_at, turn_id) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id, seq) DO UPDATE SET content_json = excluded.content_json, turn_id = excluded.turn_id
                """,
                (conversation_id, seq, json.dumps(content_dict, ensure_ascii=False), now, turn_id),
            )
            self.conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
            self.conn.commit()

    def get_history(self, conversation_id: str) -> list[dict]:
        """Return history entries ordered by seq."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT content_json FROM history_entries WHERE conversation_id = ? ORDER BY seq",
                (conversation_id,),
            ).fetchall()
        return [json.loads(r["content_json"]) for r in rows]

    # ---- Turns ----

    def create_turn(self, conversation_id: str, turn_id: str, input_data: dict, status: str = "running") -> dict:
        now = utc_now()
        with self._lock:
            seq = self.conn.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 FROM turns WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO turns (id, conversation_id, seq, status, input_json, legacy, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
                (turn_id, conversation_id, seq, status, _dumps(input_data), now, now),
            )
            self.conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
            self.conn.commit()
        return self.get_turn(turn_id)  # type: ignore[return-value]

    def get_turn(self, turn_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        return self._decode("turns", row)

    def last_turn(self, conversation_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM turns WHERE conversation_id = ? ORDER BY seq DESC LIMIT 1", (conversation_id,)
            ).fetchone()
        return self._decode("turns", row)

    def list_turns(self, conversation_id: str) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM turns WHERE conversation_id = ? ORDER BY seq", (conversation_id,)
            ).fetchall()
        return [self._decode("turns", r) for r in rows]

    def update_turn(self, turn_id: str, **fields: Any) -> dict | None:
        return self._update("turns", turn_id, fields)

    def interrupt_running_turns(self, error: str) -> None:
        """服务启动时：上次退出时还在执行的 turn 都已中断（等用户批准 / 选择的保持不变）。"""
        now = utc_now()
        with self._lock:
            self.conn.execute(
                "UPDATE steps SET status = 'cancelled', result_json = ?, finished_at = ? WHERE status = 'running' AND kind = 'tool'",
                (_dumps({"error": error}), now),
            )
            self.conn.execute("UPDATE steps SET status = 'completed', finished_at = ? WHERE status = 'running'", (now,))
            self.conn.execute("UPDATE turns SET status = 'cancelled', updated_at = ? WHERE status = 'running'", (now,))
            self.conn.commit()

    def delete_turns_from(self, conversation_id: str, seq: int) -> list[str]:
        """删除第 seq 轮及之后的所有轮（连同它们的历史、step 和后台任务），返回删掉的 turn id。"""
        with self._lock:
            ids = [r["id"] for r in self.conn.execute(
                "SELECT id FROM turns WHERE conversation_id = ? AND seq >= ?", (conversation_id, seq)
            ).fetchall()]
            if ids:
                marks = ",".join("?" * len(ids))
                self.conn.execute(f"DELETE FROM history_entries WHERE turn_id IN ({marks})", ids)  # noqa: S608
                self.conn.execute(f"DELETE FROM jobs WHERE turn_id IN ({marks})", ids)  # noqa: S608
                self.conn.execute(f"DELETE FROM turns WHERE id IN ({marks})", ids)  # noqa: S608
                self.conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (utc_now(), conversation_id))
            self.conn.commit()
        return ids

    # ---- Steps ----

    def create_step(self, turn_id: str, kind: str, status: str, **fields: Any) -> dict:
        step_id = new_id()
        values = {
            "tool": fields.get("tool"),
            "call_id": fields.get("call_id"),
            "args_json": _dumps(fields.get("args")),
            "result_json": _dumps(fields.get("result")),
            "display_json": _dumps(fields.get("display")),
            "text": fields.get("text"),
            "job_id": fields.get("job_id"),
            "started_at": fields.get("started_at", utc_now()),
            "finished_at": fields.get("finished_at"),
            "duration_ms": fields.get("duration_ms"),
        }
        with self._lock:
            seq = self.conn.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 FROM steps WHERE turn_id = ?", (turn_id,)
            ).fetchone()[0]
            self.conn.execute(
                f"INSERT INTO steps (id, turn_id, seq, kind, status, {', '.join(values)}) "  # noqa: S608
                f"VALUES (?, ?, ?, ?, ?, {', '.join('?' * len(values))})",
                (step_id, turn_id, seq, kind, status, *values.values()),
            )
            self.conn.commit()
        return self.get_step(step_id)  # type: ignore[return-value]

    def get_step(self, step_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM steps WHERE id = ?", (step_id,)).fetchone()
        return self._decode("steps", row)

    def steps_for_turn(self, turn_id: str) -> list[dict]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM steps WHERE turn_id = ? ORDER BY seq", (turn_id,)).fetchall()
        return [self._decode("steps", r) for r in rows]

    def update_step(self, step_id: str, **fields: Any) -> dict | None:
        return self._update("steps", step_id, fields)

    # ---- Jobs ----

    def create_job(self, job_id: str, conversation_id: str, turn_id: str | None, step_id: str | None,
                   tool: str, args: dict) -> dict:
        with self._lock:
            self.conn.execute(
                "INSERT INTO jobs (id, conversation_id, turn_id, step_id, tool, args_json, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)",
                (job_id, conversation_id, turn_id, step_id, tool, _dumps(args), utc_now()),
            )
            self.conn.commit()
        return self.get_job(job_id)  # type: ignore[return-value]

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._decode("jobs", row)

    def list_jobs(self, conversation_id: str, *, ids: list[str] | None = None, turn_id: str | None = None,
                  unfinished: bool = False) -> list[dict]:
        """对话里的后台任务：ids 指定时只取这些；turn_id / unfinished 同时给出时取两者的并集。"""
        query = "SELECT * FROM jobs WHERE conversation_id = ?"
        params: list[Any] = [conversation_id]
        if ids is not None:
            if not ids:
                return []
            query += f" AND id IN ({','.join('?' * len(ids))})"
            params += ids
        else:
            conditions = []
            if turn_id:
                conditions.append("turn_id = ?")
                params.append(turn_id)
            if unfinished:
                conditions.append("status IN ('queued', 'running')")
            if conditions:
                query += f" AND ({' OR '.join(conditions)})"
        with self._lock:
            rows = self.conn.execute(query + " ORDER BY created_at", params).fetchall()
        return [self._decode("jobs", r) for r in rows]

    def update_job(self, job_id: str, **fields: Any) -> dict | None:
        return self._update("jobs", job_id, fields)

    def fail_unfinished_jobs(self, error: str) -> int:
        """服务重启时，之前没跑完的后台任务都已中断。"""
        with self._lock:
            cur = self.conn.execute(
                "UPDATE jobs SET status = 'failed', error = ?, finished_at = ? WHERE status IN ('queued', 'running')",
                (error, utc_now()),
            )
            self.conn.commit()
        return cur.rowcount

    # ---- 内部 ----

    def _update(self, table: str, row_id: str, fields: dict[str, Any]) -> dict | None:
        values: dict[str, Any] = {}
        for key, value in fields.items():
            column = f"{key}_json" if f"{key}_json" in _JSON_COLUMNS[table] else key
            if column not in _UPDATABLE[table]:
                raise ValueError(f"{table}.{key} 不能修改")
            values[column] = _dumps(value) if column in _JSON_COLUMNS[table] else value
        with self._lock:
            if values:
                set_clause = ", ".join(f"{k} = ?" for k in values)
                if table == "turns":
                    set_clause += ", updated_at = ?"
                    values["updated_at"] = utc_now()
                self.conn.execute(f"UPDATE {table} SET {set_clause} WHERE id = ?", [*values.values(), row_id])  # noqa: S608
                self.conn.commit()
            row = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()  # noqa: S608
        return self._decode(table, row)

    @staticmethod
    def _decode(table: str, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        data = dict(row)
        for column in _JSON_COLUMNS.get(table, ()):
            if column in data:
                data[column.removesuffix("_json")] = _loads(data.pop(column))
        if table == "turns":
            data["legacy"] = bool(data.get("legacy"))
        return data

    # ---- Lifecycle ----

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()


# ========== 给前端的视图 ==========

def job_view(job: dict | None) -> dict | None:
    if not job:
        return None
    return {
        "id": job["id"], "turn_id": job["turn_id"], "step_id": job["step_id"], "tool": job["tool"],
        "status": job["status"], "error": job["error"], "result": job["result"], "media": job["media"] or [],
        "created_at": job["created_at"], "started_at": job["started_at"], "finished_at": job["finished_at"],
    }


def step_view(step: dict, job: dict | None = None) -> dict:
    view = {
        "id": step["id"], "turn_id": step["turn_id"], "seq": step["seq"], "kind": step["kind"], "status": step["status"],
        "started_at": step["started_at"], "finished_at": step["finished_at"], "duration_ms": step["duration_ms"],
    }
    if step["kind"] == "message":
        view["text"] = step["text"] or ""
    else:
        view.update(
            tool=step["tool"], args=step["args"] or {}, result=step["result"], display=step["display"],
            verdict=step["verdict"], job=job_view(job),
        )
    return view


def turn_view(turn: dict, steps: list[dict] | None = None) -> dict:
    view = {
        "id": turn["id"], "conversation_id": turn["conversation_id"], "seq": turn["seq"], "status": turn["status"],
        "input": turn["input"] or {"text": "", "attachments": []}, "error": turn["error"], "error_kind": turn["error_kind"],
        "legacy": turn["legacy"], "created_at": turn["created_at"], "updated_at": turn["updated_at"],
    }
    if steps is not None:
        view["steps"] = steps
    return view


def conversation_turns(db: ConversationDB, conversation_id: str) -> list[dict]:
    """对话的全部 turn（含 step 和后台任务状态），前端据此渲染。"""
    jobs = {j["id"]: j for j in db.list_jobs(conversation_id)}
    return [
        turn_view(turn, [step_view(s, jobs.get(s["job_id"])) for s in db.steps_for_turn(turn["id"])])
        for turn in db.list_turns(conversation_id)
    ]
