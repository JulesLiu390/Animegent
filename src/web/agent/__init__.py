"""对话 Agent：Session（对话）→ Turn（用户一次输入）→ Step（一段模型文字或一次工具调用）。

- session.py  turn 的执行：调用模型、执行工具、等用户批准 / 选择、停止
- tools/      工具注册表：每个工具一个声明 + 执行函数，按类型（读 / 写 / 生成 / 交互）决定怎么执行
- jobs.py     生成类工具的后台任务，模型用 check_jobs 查询结果
- prompts.py  系统提示词（只放技能目录）
- skills.py   技能：skills/ 和项目 skills/ 里的做法说明（SKILL.md），模型用 skill_load 按需读取
"""

import threading
from pathlib import Path

from src.web.db import ConversationDB

from .jobs import JobManager
from .session import Cancelled, Session, TurnRun, available_tools, normalize_interaction, normalize_mode


class Sessions:
    """内存里的对话运行时（锁、停止标记）；数据都在数据库里，随时可以重建。"""

    def __init__(self, db: ConversationDB, jobs: JobManager, projects_dir: Path) -> None:
        self.db = db
        self.jobs = jobs
        self.projects_dir = projects_dir
        self._items: dict[str, Session] = {}
        self._lock = threading.Lock()

    def get(self, conversation_id: str | None) -> Session | None:
        if not conversation_id:
            return None
        with self._lock:
            session = self._items.get(conversation_id)
            if session is None:
                conv = self.db.get_conversation(conversation_id)
                if not conv:
                    return None
                project = conv["project"]
                session = Session(self.db, self.jobs, conversation_id, None if project == "default" else self.projects_dir / project)
                self._items[conversation_id] = session
            return session

    def create(self, project_dir: Path | None, lang: str) -> Session:
        cid = self.db.create_conversation(project_dir.name if project_dir else "default", lang)
        session = Session(self.db, self.jobs, cid, project_dir)
        with self._lock:
            self._items[cid] = session
        return session

    def drop(self, conversation_id: str) -> None:
        """丢掉内存里的运行时（项目改名 / 删除后路径变了），正在跑的任务先停下。"""
        with self._lock:
            session = self._items.pop(conversation_id, None)
        if session:
            session.stop()

    def busy(self, conversation_ids: list[str]) -> list[str]:
        with self._lock:
            return [cid for cid in conversation_ids if cid in self._items and self._items[cid].run_lock.locked()]


__all__ = [
    "Cancelled", "JobManager", "Session", "Sessions", "TurnRun", "available_tools", "normalize_interaction", "normalize_mode",
]
