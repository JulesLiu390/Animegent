"""连读：把一组分镜草稿或一组成图按顺序交给模型，以第一次看的读者身份通读，找出跨条的问题（read-through 技能）。

- 草稿连读：每份草稿的标题、版式和画面指令按顺序排好，模型照着「画面指令」想象读者看到的页面。
- 成图连读：一组条漫图片按顺序发过去；同时传了草稿时，草稿放在最后，只用来判断问题的根在草稿还是成图。
- 总剧本的节奏表和每条的读者须知放在材料最后：先冷读、复述，再对照。
单独调用一次模型，主对话只收到结论和问题清单。
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from src.providers import llm
from src.providers.http import image_part

from .. import skills
from .base import Tool, ToolContext, array, obj, register, string
from .drafts import (
    _STRIP_TITLE,
    DIRECTIONS,
    LAYOUT,
    _draft_index,
    _headings,
    draft_meta,
    section,
    strip_context,
)

MAX_STRIPS = 12
_FAMILIAR = re.compile(r"^[ \t]*[-*][ \t]*读者须知[:：]?[ \t]*(.*)$", re.MULTILINE)


class ReadThroughIssue(BaseModel):
    strip: int = Field(0, description="第几条（按传进来的顺序，从 1 开始）；整组的问题填 0")
    panel: int = Field(0, description="第几格；跨条或整条的问题填 0")
    kind: str = Field("", description="读不懂 / 衔接 / 人物 / 称呼 / 连续性 / 节奏 / 重复 / 文字 / 其他")
    problem: str = Field(description="读者卡在哪里，写读者的感受")
    target: str = Field("", description="问题的根：总剧本 / 草稿 / 成图 / 不用改")
    fix: str = Field("", description="最小的改法，具体到哪一条哪一格")


class ReadThrough(BaseModel):
    story: str = Field(description="第一次看的读者读完以后复述的故事，几句话")
    verdict: str = Field(description="pass：读者能顺着读下来；minor：有几处卡顿；redo：跟不上主线")
    issues: list[ReadThroughIssue] = Field(default_factory=list)


TARGETS = ("总剧本", "草稿", "成图", "不用改")


def _title(draft: str, path: Path) -> str:
    return next((t for level, t, _, _ in _headings(draft) if level == 1), path.stem)


def _familiar(script: str, n: int | None) -> str:
    """总剧本里这一条的「读者须知」（新格式写在每条里；没有就算了）。"""
    found = strip_context(script, n) if n else None
    if not found:
        return ""
    m = _FAMILIAR.search(found.current)
    if not m:
        return ""
    lines = [m.group(1).strip()] if m.group(1).strip() else []
    rest = found.current[m.end():].splitlines()[1:]  # 跳过匹配那一行剩下的部分
    for line in rest:  # 读者须知下面缩进的几行
        if not line.startswith(("  ", "\t")) or not line.strip():
            break
        lines.append(line.strip().lstrip("-* ").strip())
    return "；".join(x for x in lines if x)


def read_through(args: dict, ctx: ToolContext) -> dict:
    drafts = [Path(p) for p in args.get("drafts") or [] if isinstance(p, str) and p]
    strips = [Path(p) for p in args.get("strips") or [] if isinstance(p, str) and p]
    if not drafts and not strips:
        return {"error": "drafts（分镜草稿）和 strips（成图）至少传一组，按阅读顺序排好"}
    if max(len(drafts), len(strips)) > MAX_STRIPS:
        return {"error": f"一次最多连读 {MAX_STRIPS} 条，分成几组读（每组和上一组重叠一条）"}
    for path in [*drafts, *strips]:
        if not path.is_file():
            return {"error": f"文件不存在: {path}"}
    texts = [p.read_text(encoding="utf-8") for p in drafts]

    script_path = Path(args["script_path"]) if args.get("script_path") else None
    if script_path is None and texts:
        ref = draft_meta(texts[0]).get("script")
        if ref:
            script_path = Path(ref) if Path(ref).is_absolute() else (ctx.project_dir / ref if ctx.project_dir else Path(ref))
    script = script_path.read_text(encoding="utf-8") if script_path and script_path.is_file() else ""

    try:
        system = skills.get("read-through", ctx.project_dir).body()
    except skills.SkillError as exc:
        return {"error": f"读取连读的技能出错：{exc}"}
    system += "\n\nWrite story, problem and fix in English." if ctx.lang == "en" else "\n\n用中文写复述、问题和改法。"

    parts: list[dict] = []
    items: list[dict] = []
    if strips:
        parts.append({"type": "text", "text": f"成图连读：下面是按顺序排好的 {len(strips)} 条条漫，先只看图，像第一次看的读者那样读下去。"})
        for i, path in enumerate(strips, start=1):
            parts += [{"type": "text", "text": f"第 {i} 条（{path.name}）"}, image_part(path)]
            items.append({"strip": i, "image": str(path)})
    tail = ""
    if drafts:
        blocks = []
        for i, (path, text) in enumerate(zip(drafts, texts, strict=True), start=1):
            blocks.append(
                f"【第 {i} 条：{_title(text, path)}】\n"
                f"版式：\n{(section(text, LAYOUT) or '').strip()}\n\n画面指令：\n{(section(text, DIRECTIONS) or '').strip()}"
            )
            if i <= len(items):
                items[i - 1]["draft"] = str(path)
            else:
                items.append({"strip": i, "draft": str(path)})
        joined = "\n\n".join(blocks)
        if strips:
            tail += f"看完图、复述完故事以后，再看这些分镜草稿，只用来判断问题的根在草稿还是成图：\n\n{joined}\n\n"
        else:
            parts.append({"type": "text", "text": (
                f"草稿连读：下面是按顺序排好的 {len(drafts)} 条分镜草稿。照着每一格的「画面指令」想象读者会看到的页面，"
                f"像第一次看的读者那样读下去。\n\n{joined}"
            )})
    if script:
        first = next((start for _, title, start, _ in _headings(script) if _STRIP_TITLE.match(title)), len(script))
        rhythm = section(script[:first], ("节奏表",)) or ""
        familiar = [
            f"第 {i} 条：{f}" for i, text in enumerate(texts, start=1)
            if (f := _familiar(script, _draft_index(text, drafts[i - 1])))
        ]
        if rhythm:
            tail += f"复述完以后再对照总剧本的节奏表：\n{rhythm}\n\n"
        if familiar:
            tail += "每条的读者须知：\n" + "\n".join(familiar) + "\n\n"
    if args.get("notes"):
        tail += f"这次特别要看的：{str(args['notes']).strip()}\n\n"
    parts.append({"type": "text", "text": tail + "按技能里的步骤写：先复述故事，再列出跨条的问题，最后给结论。"})

    review = llm.generate_json("vision" if strips else "chat", parts, ReadThrough, system=system, max_retries=2, timeout=300)
    issues = [i.model_dump() for i in review.issues if i.problem.strip()][:12]
    for issue in issues:
        issue["target"] = next((t for t in TARGETS if t in issue["target"]), "不用改")
    verdict = review.verdict.strip().lower()
    verdict = verdict if verdict in ("pass", "minor", "redo") else ("redo" if any(i["target"] == "总剧本" for i in issues) else "minor")
    return {"verdict": verdict, "story": review.story, "issues": issues, "items": items}


register(
    Tool(
        name="read_through",
        description=(
            "连读：把一组条漫按顺序连起来读一遍，以第一次看的读者身份复述读到的故事，找出跨条的问题"
            "（人物有没有交代、称呼说法有没有解释、时间和回忆的切换跟不跟得上、节奏和版式有没有重复），"
            "并指出根在总剧本、草稿还是成图。一组分镜草稿写完、生成之前传 drafts；一组条漫生成完以后传 strips"
            "（可以同时传 drafts，用来判断根在哪）。单独调用一次模型，只返回结论和问题清单。按 read-through 技能来。"
        ),
        parameters=obj(
            {
                "drafts": array(string("分镜草稿路径"), "分镜草稿，按阅读顺序"),
                "strips": array(string("条漫图片路径"), "生成好的条漫，按阅读顺序"),
                "script_path": string("可选：总剧本路径；不传就用第一份草稿记录的总剧本"),
                "notes": string("可选：这次特别要看的地方"),
            },
        ),
        run=read_through,
        kind="read",
        modes=frozenset({"comic"}),
    ),
)
