"""后台生成任务。

生成类工具（图片 / 视频）调用后立即返回 job_id，真正的生成在这里的后台线程里跑，状态和结果写进数据库：
- 模型用 check_jobs 查询或等待结果
- 前端在对话流里收到 job 事件；流结束后轮询 /api/conversations/{id}/jobs
同一用途同时执行的任务数按服务商设置的并发上限（默认 3），其余的排队。
check_jobs 可以等全部结束（until="all"），也可以等其中任何一个结束就返回（until="any"），先处理好了的那个。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime

from src.providers import settings as provider_settings
from src.web.db import JOB_UNFINISHED, ConversationDB, job_view, utc_now

from .tools import Cancelled, Tool, ToolContext, collect_media, execute

logger = logging.getLogger(__name__)

FINISHED = ("succeeded", "failed", "cancelled")


class JobManager:
    def __init__(self, db: ConversationDB) -> None:
        self.db = db
        # 任务状态一变就通知等待的 check_jobs；同时保护下面的计数
        self._cond = threading.Condition()
        self._running: dict[str, int] = defaultdict(int)
        self._listeners: dict[str, list[Callable[[dict], None]]] = defaultdict(list)
        # 已经通过 check_jobs 把结果交给模型的任务（until="any" 只等还没交过结果的）
        self._delivered: dict[str, set[str]] = defaultdict(set)

    def recover(self) -> None:
        """服务启动时调用：上次退出时还没跑完的任务都已中断。"""
        interrupted = self.db.fail_unfinished_jobs("服务重启，任务中断")
        if interrupted:
            logger.warning(f"{interrupted} 个后台任务因服务重启中断")

    # ---- 提交 / 取消 ----

    def submit(self, tool: Tool, args: dict, ctx: ToolContext, step_id: str | None) -> dict:
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        job = self.db.create_job(job_id, ctx.conversation_id or "", ctx.turn_id, step_id, tool.name, args)
        # 守护线程：服务退出时不用等还在生成的图片
        run_ctx = ToolContext(project_dir=ctx.project_dir, lang=ctx.lang, conversation_id=ctx.conversation_id, turn_id=ctx.turn_id)
        threading.Thread(target=self._run, args=(job_id, tool, args, run_ctx), daemon=True, name=job_id).start()
        return job

    def cancel(self, job_id: str) -> dict | None:
        """取消还在排队的任务；已经开始生成的没法中途停下，会照常完成。"""
        job = self.db.get_job(job_id)
        if job and job["status"] == "queued":
            job = self.db.update_job(job_id, status="cancelled", error="已取消", finished_at=utc_now())
            self._notify(job)
        return job

    def cancel_queued(self, conversation_id: str, turn_ids: list[str] | None = None) -> None:
        for job in self.db.list_jobs(conversation_id, unfinished=True):
            if job["status"] == "queued" and (turn_ids is None or job["turn_id"] in turn_ids):
                self.cancel(job["id"])

    # ---- 执行 ----

    def _run(self, job_id: str, tool: Tool, args: dict, ctx: ToolContext) -> None:
        role = tool.role
        with self._cond:
            while True:
                job = self.db.get_job(job_id)
                if job is None or job["status"] != "queued":
                    return  # 排队时被取消或删除了
                if self._running[role] < provider_settings.concurrency(role):
                    break
                self._cond.wait(1.0)
            self._running[role] += 1
        job = None
        try:
            job = self.db.update_job(job_id, status="running", started_at=utc_now())
            if job is None:
                return
            self._notify(job)
            result = execute(tool, args, ctx)
            error = result.get("error")
            job = self.db.update_job(
                job_id,
                status="failed" if error else "succeeded",
                result=result,
                media=[] if error else collect_media(tool.name, result),
                error=str(error) if error else None,
                finished_at=utc_now(),
            )
        except Exception as exc:  # execute() 已经兜底工具本身的异常，这里防数据库等意外
            logger.exception(f"后台任务 {job_id} 出错")
            job = self.db.update_job(job_id, status="failed", error=str(exc) or type(exc).__name__, finished_at=utc_now())
        finally:
            with self._cond:
                self._running[role] -= 1
                self._cond.notify_all()
        if job:
            self._notify(job)

    # ---- 查询 / 等待 ----

    def wait(self, conversation_id: str, job_ids: list[str] | None, *, turn_id: str | None, timeout: float,
             cancel_event: threading.Event | None = None, until: str = "all") -> list[dict]:
        """等到这些任务全部结束或超时；用户停止时抛出 Cancelled。

        until="any"：有一个任务结束、而且它的结果还没交给过模型，就返回。
        不指定 job_ids 时：这一轮发起的任务 + 所有还没结束的任务。
        """
        deadline = time.monotonic() + timeout
        waiting: set[str] | None = None  # 开始等时还没结束的任务
        while True:
            if cancel_event and cancel_event.is_set():
                raise Cancelled()
            if job_ids:
                rows = self.db.list_jobs(conversation_id, ids=job_ids)
            else:
                rows = self.db.list_jobs(conversation_id, turn_id=turn_id, unfinished=True)
                # 别的轮次发起的任务结束后不在上面的列表里了，单独查回来，才知道它结束了
                missing = sorted((waiting or set()) - {r["id"] for r in rows})
                if missing:
                    rows += self.db.list_jobs(conversation_id, ids=missing)
            if waiting is None:
                waiting = {r["id"] for r in rows if r["status"] not in FINISHED}
            remaining = deadline - time.monotonic()
            done = all(r["status"] in FINISHED for r in rows)
            if until == "any":
                with self._cond:
                    delivered = self._delivered[conversation_id]
                    done = done or any(r["status"] in FINISHED and r["id"] not in delivered for r in rows)
            if done or not waiting or remaining <= 0:
                return rows
            with self._cond:
                self._cond.wait(min(remaining, 0.5))

    def deliver(self, conversation_id: str, rows: list[dict]) -> None:
        """把任务状态交给模型，记下哪些任务的结果已经交过了。"""
        with self._cond:
            self._delivered[conversation_id].update(r["id"] for r in rows if r["status"] in FINISHED)

    @staticmethod
    def report(rows: list[dict], requested: list[str] | None = None) -> dict:
        """交给模型的任务状态。"""
        jobs = []
        for r in rows:
            item: dict = {"job_id": r["id"], "tool": r["tool"], "status": r["status"]}
            if r["status"] == "succeeded":
                item["result"] = r["result"]
            elif r["status"] in ("failed", "cancelled"):
                item["error"] = r["error"] or r["status"]
            elif r["started_at"]:
                item["elapsed_seconds"] = round((datetime.fromisoformat(utc_now()) - datetime.fromisoformat(r["started_at"])).total_seconds())
            jobs.append(item)
        known = {r["id"] for r in rows}
        jobs += [{"job_id": i, "status": "unknown", "error": "没有这个任务"} for i in requested or [] if i not in known]
        unfinished = sum(1 for r in rows if r["status"] in JOB_UNFINISHED)
        out: dict = {"jobs": jobs, "unfinished": unfinished}
        if unfinished:
            out["message"] = f"还有 {unfinished} 个任务没完成，可以再调用 check_jobs 继续等待。"
        elif not jobs:
            out["message"] = "没有后台任务。"
        return out

    # ---- 通知前端 ----

    def subscribe(self, conversation_id: str, listener: Callable[[dict], None]) -> None:
        with self._cond:
            self._listeners[conversation_id].append(listener)

    def unsubscribe(self, conversation_id: str, listener: Callable[[dict], None]) -> None:
        with self._cond:
            listeners = self._listeners.get(conversation_id, [])
            if listener in listeners:
                listeners.remove(listener)
            if not listeners:
                self._listeners.pop(conversation_id, None)

    def _notify(self, job: dict) -> None:
        with self._cond:
            self._cond.notify_all()
            listeners = list(self._listeners.get(job["conversation_id"], []))
        event = {"event": "job", "job": job_view(job)}
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                logger.exception("job listener failed")
