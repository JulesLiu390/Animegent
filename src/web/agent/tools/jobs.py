"""check_jobs：查询后台生成任务（生成类工具调用后立即返回 job_id，图片在后台生成）。"""

from __future__ import annotations

from .base import Tool, ToolContext, array, integer, obj, register, string

MAX_WAIT_SECONDS = 120


def check_jobs(args: dict, ctx: ToolContext) -> dict:
    if ctx.jobs is None or not ctx.conversation_id:
        return {"error": "当前没有后台任务"}
    ids = [i for i in args.get("job_ids") or [] if isinstance(i, str) and i]
    try:
        wait = int(args.get("wait_seconds", 60))
    except (TypeError, ValueError):
        wait = 60
    wait = max(0, min(wait, MAX_WAIT_SECONDS))
    rows = ctx.jobs.wait(ctx.conversation_id, ids or None, turn_id=ctx.turn_id, timeout=wait, cancel_event=ctx.cancel_event)
    return ctx.jobs.report(rows, requested=ids)


register(
    Tool(
        name="check_jobs",
        description=(
            "查询后台生成任务的状态和结果。生成类工具（风格化角色、生成/编辑素材、生成条漫）调用后立即返回 job_id，"
            "图片在后台生成；要用到生成结果（展示图片、用新角色画条漫）之前，先用本工具等待并拿到结果。"
            "wait_seconds 大于 0 时会一直等到这些任务全部结束或超时。"
        ),
        parameters=obj({
            "job_ids": array(string("任务 id"), "要查询的任务 id；不填则查询这一轮发起的和所有还没结束的任务"),
            "wait_seconds": integer(f"最多等待多少秒（0-{MAX_WAIT_SECONDS}，默认 60）；0 表示立即返回当前状态"),
        }),
        run=check_jobs,
        kind="read",
    ),
)
