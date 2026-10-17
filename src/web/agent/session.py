"""对话运行时：Session（对话）→ Turn（用户一次输入）→ Step（一段模型文字或一次工具调用）。

一个 turn 从用户发出消息开始，到控制权交还用户为止：
- completed           模型说完了，不再调用工具（后台生成任务可能还在跑，模型用 check_jobs 等结果）
- awaiting_approval   「生成前确认」模式下，生成类工具等用户批准
- awaiting_input      选人脸 / 选角色，等用户在卡片里选
- cancelled / failed  被停止 / 出错
等用户时，用户的回应（批准、拒绝、选择）让同一个 turn 继续；用户没回应就发了新消息，等待中的调用按「用户没有处理」回给模型。

数据都在数据库里，Session 只负责同一时间只跑一个 turn、以及停止。
"""

from __future__ import annotations

import copy
import logging
import queue
import threading
import time
from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from src.providers import llm
from src.providers import settings as provider_settings
from src.providers.http import image_part
from src.web import features
from src.web.db import STEP_PENDING, ConversationDB, step_view, turn_view, utc_now
from src.web.serializer import history_entry_from_json, history_entry_to_json

from .jobs import JobManager
from .prompts import build_system_prompt
from .tools import Cancelled, Tool, ToolContext, collect_media, execute, for_mode, get, has_choices

logger = logging.getLogger(__name__)

MAX_ROUNDS = 40
INTERACTIONS = ("ask", "confirm", "auto")


def normalize_mode(mode: str | None) -> str:
    # 分镜模式休眠（features.STORYBOARD 关闭）时一律按条漫运行
    return "storyboard" if mode == "storyboard" and features.STORYBOARD else "comic"


def normalize_interaction(value: str | None) -> str:
    """ask 讨论 / confirm 生成前确认 / auto 自动执行；旧版的 edit / plan 都按「生成前确认」处理。"""
    return value if value in INTERACTIONS else "confirm"


def available_tools(mode: str, interaction: str) -> list[Tool]:
    tools = for_mode(mode)
    return [t for t in tools if t.kind == "read"] if interaction == "ask" else tools


def attachment_text(files: list[dict]) -> str:
    """非图片附件（md / json / 视频）转成发给模型的文字。"""
    out = []
    for f in files:
        if f.get("fileType") == "video":
            out.append(f"[附件视频: {f.get('path', '')}]")
        else:
            label = "JSON" if f.get("fileType") == "json" else "Markdown"
            out.append(f"[附件: {f.get('name', '')} ({label}) {f.get('path', '')}]\n{f.get('content') or '(无内容)'}")
    return "\n\n".join(out)


def user_message(input_data: dict) -> dict:
    """turn 的输入 → 发给模型的用户消息（图片按路径引用，发送时再读取）。"""
    attachments = input_data.get("attachments") or []
    images = [a for a in attachments if not a.get("fileType") or a.get("fileType") == "image"]
    files = [a for a in attachments if a not in images]
    parts: list[dict] = []
    for att in images:
        p = Path(att.get("path") or "")
        if p.is_file():
            parts.append({"type": "text", "text": f"[图片路径: {p}]"})
            parts.append(image_part(p))
    text = "\n\n".join(filter(None, [attachment_text(files), input_data.get("text") or ""]))
    parts.append({"type": "text", "text": text or "请分析这些图片"})
    return {"role": "user", "parts": parts}


class Session:
    """一个对话的运行时。turn 相关的方法都要在持有 run_lock 时调用（由 API 层负责）。"""

    def __init__(self, db: ConversationDB, jobs: JobManager, conversation_id: str, project_dir: Path | None) -> None:
        self.db = db
        self.jobs = jobs
        self.id = conversation_id
        self.project_dir = project_dir
        self.run_lock = threading.Lock()
        self.cancel_event = threading.Event()

    def stop(self) -> None:
        self.cancel_event.set()

    # ---- turn ----

    def send(self, turn_id: str, input_data: dict, *, lang: str, mode: str | None, interaction: str | None) -> Iterator[dict]:
        """用户发了一条新消息：开始一个新 turn。上一个 turn 还在等用户时先把它了结。"""
        last = self.db.last_turn(self.id)
        if last and last["status"] in ("awaiting_approval", "awaiting_input"):
            yield from TurnRun(self, last, lang=lang, mode=mode, interaction=interaction).abandon(
                "用户没有处理，直接发送了新消息", "completed"
            )
        turn = self.db.create_turn(self.id, turn_id, input_data)
        yield {"event": "turn", "turn": turn_view(turn, [])}
        yield from TurnRun(self, turn, lang=lang, mode=mode, interaction=interaction).start()

    def resume(self, turn: dict, responses: dict[str, dict], *, lang: str, mode: str | None, interaction: str | None) -> Iterator[dict]:
        """用户批准 / 拒绝了生成，或者在卡片里做了选择：同一个 turn 继续。"""
        yield from TurnRun(self, turn, lang=lang, mode=mode, interaction=interaction).resume(responses)

    def rewind(self, turn: dict) -> list[str]:
        """删掉这一轮及之后的内容（重试、编辑、删除消息），模型看到的历史和界面保持一致。"""
        later = [t["id"] for t in self.db.list_turns(self.id) if t["seq"] >= turn["seq"]]
        self.jobs.cancel_queued(self.id, turn_ids=later)
        return self.db.delete_turns_from(self.id, turn["seq"])

    def settle(self, reason: str) -> Iterator[dict]:
        """没有任务在跑、但最后一轮在等用户时被停止：等待中的调用按停止处理。"""
        last = self.db.last_turn(self.id)
        if last and last["status"] in ("awaiting_approval", "awaiting_input"):
            yield from TurnRun(self, last, lang="zh", mode=None, interaction=None).abandon(reason, "cancelled")


class TurnRun:
    """执行一个 turn：调用模型、执行工具，直到模型不再调用工具，或者需要等用户。"""

    def __init__(self, session: Session, turn: dict, *, lang: str, mode: str | None, interaction: str | None) -> None:
        self.session = session
        self.db = session.db
        self.turn = turn
        self.turn_id: str = turn["id"]
        self.lang = lang
        self.mode = normalize_mode(mode)
        self.interaction = normalize_interaction(interaction)
        self.history = [history_entry_from_json(d) for d in self.db.get_history(session.id)]
        self.tools = available_tools(self.mode, self.interaction)
        self.ctx = ToolContext(
            project_dir=session.project_dir, lang=lang, mode=self.mode, conversation_id=session.id, turn_id=self.turn_id,
            jobs=session.jobs, cancel_event=session.cancel_event,
        )
        # 模型最近一次回复里的工具调用：[(call, step)]，全部有结果后一起回给模型
        self._batch: list[list[Any]] = []
        # 工具画出的图：只附在下一次请求里给模型看
        self._observations: list[dict] = []

    def _t(self, zh: str, en: str) -> str:
        return en if self.lang == "en" else zh

    # ---- 入口 ----

    def start(self) -> Iterator[dict]:
        try:
            # 没配置对话模型时直接报错，不往历史里写半截消息
            provider_settings.resolve("chat")
        except provider_settings.NotConfiguredError as e:
            yield from self._set_status("failed", error=str(e), error_kind="config")
            return
        self._append_history(user_message(self.turn["input"] or {}))
        yield from self._guard(self._loop())

    def resume(self, responses: dict[str, dict]) -> Iterator[dict]:
        def body() -> Iterator[dict]:
            self._batch = self._load_batch()
            yield from self._set_status("running")
            yield from self._apply_responses(responses)
            if self._pending():
                yield from self._pause()
                return
            self._answer_batch()
            yield from self._loop()

        yield from self._guard(body())

    def abandon(self, reason: str, status: str) -> Iterator[dict]:
        """turn 在等用户时被放弃：等待中的调用按 reason 回给模型，保证历史里每个调用都有结果。"""
        self._batch = self._load_batch()
        for pair in self._batch:
            step = pair[1]
            if step and step["status"] in STEP_PENDING:
                pair[1] = self.db.update_step(step["id"], status="cancelled", result={"error": reason}, finished_at=utc_now())
                yield self._step_event(pair[1])
        if self._batch:
            self._answer_batch()
        yield from self._set_status(status)

    # ---- 主循环 ----

    def _guard(self, gen: Iterator[dict]) -> Iterator[dict]:
        try:
            yield from gen
        except Cancelled:
            yield from self._on_cancel()
        except provider_settings.NotConfiguredError as e:
            yield from self._on_error(str(e), "config")
        except Exception as e:
            logger.exception("turn 执行出错")
            yield from self._on_error(str(e) or type(e).__name__, "generic")

    def _loop(self) -> Iterator[dict]:
        yield from self._set_status("running")
        schemas = [t.schema for t in self.tools]
        available = {t.name: t for t in self.tools}
        for _ in range(MAX_ROUNDS):
            self._check_cancel()
            reply = yield from self._model_round(self._system_prompt(), schemas)
            calls = [p for p in reply["parts"] if p["type"] == "function_call"]
            if not calls:
                yield from self._set_status("completed")
                return
            yield from self._run_calls(calls, available)
            if self._pending():
                yield from self._pause()
                return
            self._answer_batch()
        yield from self._note(self._t("（这一轮的工具调用次数达到上限，先停在这里）", "(Reached the tool-call limit for this turn.)"))
        yield from self._set_status("completed")

    def _system_prompt(self) -> str:
        # 每轮重新生成：素材清单、后台任务会随着工具执行变化
        return build_system_prompt(
            mode=self.mode, interaction=self.interaction, lang=self.lang, project_dir=self.session.project_dir,
            tools=for_mode(self.mode), unfinished_jobs=self.db.list_jobs(self.session.id, unfinished=True),
        )

    def _model_round(self, system: str, schemas: list[dict]) -> Iterator[dict]:
        """流式输出模型回复；文字记为一个 message step。返回模型消息。"""
        step: dict | None = None
        streamed: list[str] = []
        last_flush = time.monotonic()
        reply: dict = {"role": "model", "parts": []}
        messages = self.history
        if self._observations and self.history:
            last = self.history[-1]
            messages = [*self.history[:-1], {**last, "parts": [*last["parts"], *self._observations]}]
            self._observations = []
        try:
            for event in self._interruptible(llm.stream_chat("chat", system, messages, schemas)):
                if event["type"] == "text":
                    if step is None:
                        step = self.db.create_step(self.turn_id, "message", "running", text="")
                        yield self._step_event(step)
                    streamed.append(event["text"])
                    yield {"event": "delta", "step_id": step["id"], "text": event["text"]}
                    if time.monotonic() - last_flush > 1.5:  # 中途刷新页面也能看到已经输出的部分
                        self.db.update_step(step["id"], text="".join(streamed))
                        last_flush = time.monotonic()
                elif event["type"] == "message":
                    reply = event["message"]
        except Cancelled:
            # 停止时已经输出的文字也记进历史，模型之后知道自己说到了哪里
            if streamed:
                text = "".join(streamed)
                self._append_history({"role": "model", "parts": [{"type": "text", "text": text}]})
                yield self._step_event(self.db.update_step(step["id"], status="completed", text=text, finished_at=utc_now()))
            raise

        text = "".join(p.get("text", "") for p in reply["parts"] if p["type"] == "text") or "".join(streamed)
        if step is None and text.strip():
            step = self.db.create_step(self.turn_id, "message", "running", text="")
        if step is not None:
            yield self._step_event(self.db.update_step(step["id"], status="completed", text=text, finished_at=utc_now()))
        if reply["parts"]:
            self._append_history(reply)
        return reply

    def _run_calls(self, calls: list[dict], available: dict[str, Tool]) -> Iterator[dict]:
        self._batch = []
        runnable = []
        for call in calls:
            tool = available.get(call["name"])
            args = copy.deepcopy(call.get("args") or {})
            fields: dict[str, Any] = {"tool": call["name"], "call_id": call["id"], "args": args}
            if tool is None:
                # 当前模式下不能用的工具（例如讨论模式下的生成类工具）：不执行，但也要给出结果
                step = self.db.create_step(self.turn_id, "tool", "failed", result={"error": self._blocked(call["name"])},
                                           finished_at=utc_now(), **fields)
            elif tool.kind == "generate" and self.interaction == "confirm":
                step = self.db.create_step(self.turn_id, "tool", "pending_approval", **fields)
            else:
                step = self.db.create_step(self.turn_id, "tool", "running", **fields)
                runnable.append((tool, args, step))
            self._batch.append([call, step])
            yield self._step_event(step)
        yield from self._execute(runnable)

    def _blocked(self, name: str) -> str:
        if self.interaction == "ask":
            return self._t("讨论模式下不执行这个工具，只能读取内容", "Not available in Ask mode (read-only)")
        return self._t(f"当前不能使用 {name}", f"{name} is not available right now")

    def _execute(self, items: list[tuple[Tool, dict, dict]]) -> Iterator[dict]:
        """执行工具（多个时并发），按完成顺序更新 step；生成类工具提交到后台，立即返回 job_id。"""
        if not items:
            return

        def run(tool: Tool, args: dict, step: dict) -> tuple[dict, dict]:
            t0 = time.time()
            if tool.kind == "generate":
                job = self.session.jobs.submit(tool, args, self.ctx, step["id"])
                result = {
                    "job_id": job["id"], "status": "queued",
                    "message": "已在后台开始生成。需要结果时调用 check_jobs（可以设置 wait_seconds 等待完成）。",
                }
                fields: dict[str, Any] = {"status": "completed", "result": result, "job_id": job["id"]}
            else:
                result = execute(tool, args, self.ctx)
                if tool.kind == "interactive" and has_choices(result):
                    # 选项交给界面展示，用户选完，选择结果才是交给模型的工具结果
                    return step, {"status": "awaiting_input", "display": result}
                media = collect_media(tool.name, result)
                fields = {"status": "failed" if result.get("error") else "completed", "result": result,
                          "display": {"media": media} if media else None}
            fields.update(finished_at=utc_now(), duration_ms=round((time.time() - t0) * 1000))
            return step, fields

        workers = 1 if len(items) == 1 else min(len(items), 8)
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            pending = {pool.submit(run, *item) for item in items}
            while pending:
                done, pending = wait(pending, timeout=0.3, return_when=FIRST_COMPLETED)
                for future in done:
                    step, fields = future.result()
                    updated = self.db.update_step(step["id"], **fields)
                    for pair in self._batch:
                        if pair[1] and pair[1]["id"] == step["id"]:
                            pair[1] = updated
                    yield self._step_event(updated)
                self._check_cancel()
        finally:
            # 停止时不等还在跑的工具，结果直接丢弃
            pool.shutdown(wait=False, cancel_futures=True)

    def _apply_responses(self, responses: dict[str, dict]) -> Iterator[dict]:
        runnable = []
        for pair in self._batch:
            step = pair[1]
            if not step or step["id"] not in responses or step["status"] not in STEP_PENDING:
                continue
            response = responses[step["id"]] or {}
            tool = get(step["tool"])
            if step["status"] == "pending_approval":
                if response.get("approve") and tool:
                    step = self.db.update_step(step["id"], status="running")
                    runnable.append((tool, step["args"] or {}, step))
                else:
                    note = str(response.get("note") or "").strip()
                    error = self._t("用户没有批准这次调用", "The user declined this call")
                    if note:
                        error += self._t(f"。用户的说明：{note}", f". The user said: {note}")
                    step = self.db.update_step(step["id"], status="rejected", result={"error": error}, finished_at=utc_now())
            else:
                display = step["display"] or {}
                value = response.get("value")
                result = tool.on_input(value, display) if tool and tool.on_input else {"value": value}
                step = self.db.update_step(step["id"], status="completed", result=result, finished_at=utc_now())
            pair[1] = step
            yield self._step_event(step)
        yield from self._execute(runnable)

    def _pending(self) -> bool:
        return any(pair[1] and pair[1]["status"] in STEP_PENDING for pair in self._batch)

    def _pause(self) -> Iterator[dict]:
        waiting_input = any(pair[1] and pair[1]["status"] == "awaiting_input" for pair in self._batch)
        yield from self._set_status("awaiting_input" if waiting_input else "awaiting_approval")

    def _load_batch(self) -> list[list[Any]]:
        """历史最后一条是模型的工具调用、还没有结果时，找出对应的 step（等用户时的那一批调用）。"""
        last = self.history[-1] if self.history else None
        if not last or last["role"] != "model":
            return []
        calls = [p for p in last["parts"] if p["type"] == "function_call"]
        steps = {s["call_id"]: s for s in self.db.steps_for_turn(self.turn_id) if s["call_id"]}
        return [[call, steps.get(call["id"])] for call in calls]

    def _answer_batch(self) -> None:
        """把这一批调用的结果按调用顺序写进历史。"""
        stopped = {"error": self._t("用户已停止", "Stopped by the user")}
        parts = [
            {"type": "function_response", "id": call["id"], "name": call["name"],
             "response": (step or {}).get("result") or stopped}
            for call, step in self._batch
        ]
        if parts:
            self._append_history({"role": "user", "parts": parts})
            self._observations = self._result_images()
        self._batch = []

    def _result_images(self) -> list[dict]:
        """画图类工具的结果图片。不写进历史：以后每轮都重发太费 token，模型下一轮看过、要改的话会自己重画。"""
        parts: list[dict] = []
        for call, step in self._batch:
            tool = get(call["name"])
            path = ((step or {}).get("result") or {}).get("output_path")
            if not (tool and tool.model_sees_output and step["status"] == "completed" and isinstance(path, str) and Path(path).is_file()):
                continue
            # observation：Gemini 适配器据此知道这不是用户发的新消息；OpenAI 格式里它是一条用户消息，所以文字里写明是自动附上的
            label = self._t(
                f"[自动附上的工具结果，不是用户发来的消息：{call['name']} 画出的图 {path}。看完接着做手上的任务。]",
                f"[Attached automatically, not a message from the user: the image {call['name']} drew, {path}. Look at it and carry on.]",
            )
            parts.append({"type": "text", "text": label, "observation": True})
            parts.append({**image_part(path), "observation": True})
        return parts

    # ---- 停止 / 出错 ----

    def _on_cancel(self) -> Iterator[dict]:
        stopped = {"error": self._t("用户已停止", "Stopped by the user")}
        if not self._batch:
            self._batch = self._load_batch()
        for pair in self._batch:
            step = pair[1]
            if step and step["status"] in ("running", *STEP_PENDING):
                pair[1] = self.db.update_step(step["id"], status="cancelled", result=stopped, finished_at=utc_now())
                yield self._step_event(pair[1])
        if self._batch:
            self._answer_batch()
        self.session.jobs.cancel_queued(self.session.id, turn_ids=[self.turn_id])
        yield from self._set_status("cancelled")

    def _on_error(self, message: str, kind: str) -> Iterator[dict]:
        if not self._batch:
            self._batch = self._load_batch()
        for pair in self._batch:
            step = pair[1]
            if step and step["status"] in ("running", *STEP_PENDING):
                pair[1] = self.db.update_step(step["id"], status="failed", result={"error": message}, finished_at=utc_now())
                yield self._step_event(pair[1])
        if self._batch:
            self._answer_batch()
        yield from self._set_status("failed", error=message, error_kind=kind)

    def _check_cancel(self) -> None:
        if self.session.cancel_event.is_set():
            raise Cancelled()

    def _interruptible(self, events: Iterator[dict]) -> Iterator[dict]:
        """在后台线程里读取模型的流式输出：用户停止时不必等网络请求返回。"""
        items: queue.Queue = queue.Queue()
        cancel = self.session.cancel_event

        def pump() -> None:
            try:
                for item in events:
                    items.put(("item", item))
                    if cancel.is_set():
                        break
                items.put(("end", None))
            except BaseException as exc:  # 交给读取方所在线程抛出
                items.put(("error", exc))
            finally:
                close = getattr(events, "close", None)
                if close:
                    close()

        threading.Thread(target=pump, daemon=True, name="llm-stream").start()
        while True:
            try:
                kind, value = items.get(timeout=0.25)
            except queue.Empty:
                self._check_cancel()
                continue
            self._check_cancel()  # 输出很快时队列一直有数据，也要及时响应停止
            if kind == "item":
                yield value
            elif kind == "error":
                raise value
            else:
                return

    # ---- 持久化 / 事件 ----

    def _append_history(self, entry: dict) -> None:
        seq = len(self.history)
        self.history.append(entry)
        self.db.append_history(self.session.id, seq, history_entry_to_json(entry), self.turn_id)

    def _set_status(self, status: str, **fields: Any) -> Iterator[dict]:
        if self.turn["status"] == status and not fields:
            return
        self.turn = self.db.update_turn(self.turn_id, status=status, **fields) or self.turn
        yield {"event": "turn", "turn": turn_view(self.turn)}

    def _note(self, text: str) -> Iterator[dict]:
        step = self.db.create_step(self.turn_id, "message", "completed", text=text, finished_at=utc_now())
        yield self._step_event(step)

    def _step_event(self, step: dict) -> dict:
        job = self.db.get_job(step["job_id"]) if step.get("job_id") else None
        return {"event": "step", "step": step_view(step, job)}


__all__ = ["Cancelled", "Session", "TurnRun", "available_tools", "normalize_interaction", "normalize_mode"]
