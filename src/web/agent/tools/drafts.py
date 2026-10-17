"""分镜草稿（日漫的ネーム）：总剧本 → 每条一份分镜草稿 → 生图 → 对照草稿检查成图。

- draft_strip：单独调用对话模型给一条写分镜草稿，再按草稿的「版式」一节写 PIL 代码画版式草图，
  然后像编辑看ネーム一样，带着草图把草稿检查、改一遍。这几步都在工具里完成，主对话只收到摘要和草图，
  二十几条的草稿不会堆进主对话的历史。
- review_comic_strip：生成的条漫对照分镜草稿检查，返回问题清单。
- generate_comic_strip 传 draft_path 时，用这里的函数读出「画面指令」、版式草图和总剧本的「画面总则」。

写法、格式和检查清单来自技能 strip-draft、layout-sketch、strip-review（见 strip_guide.py 和 skills.py）。

草稿文件的格式（标题下面两行由工具写入，生成时据此找到总剧本和版式草图）：
    # 第3条 分镜草稿｜标题
    > 总剧本：output/scripts/story.md
    > 版式草图：output/layouts/strip_3.png
    ## 构思 / ## 版式 / ## 逐格演出 / ## 自检 / ## 画面指令（最后一节，生图模型只看这一节）
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, Field

from src.providers import llm
from src.providers.http import image_part
from src.tools import pil_sandbox, strip_image

from .. import skills, strip_guide
from .base import Cancelled, Tool, ToolContext, array, integer, obj, register, string

DRAFT_DIR = Path("output") / "scripts" / "strips"
LAYOUT_DIR = Path("output") / "layouts"
SKETCH_SIZE = (900, 1600)  # 和 draw_with_pil 一样：9:16
CODE_ATTEMPTS = 3  # 草图代码跑不通时，带着报错让模型改，最多跑这么多次
LLM_TIMEOUT = 300.0

# 解析时中英文标题都认
CONCEPT = ("构思", "Concept")
LAYOUT = ("版式", "Layout")
CHECK = ("自检", "Self-check")
DIRECTIONS = ("画面指令", "Panel directions")
VISUAL_RULES = ("画面总则", "Visual rules")

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
_FENCE = re.compile(r"^```.*?^```[^\n]*$", re.MULTILINE | re.DOTALL)
_STRIP_TITLE = re.compile(r"(?:第\s*0*(\d+)\s*条|strip\s*#?\s*0*(\d+)\b)", re.IGNORECASE)
_PANEL_TITLE = re.compile(r"(?:第\s*0*(\d+)\s*格|panel\s*#?\s*0*(\d+)\b)", re.IGNORECASE)
_META_LINE = re.compile(r"^>\s*(总剧本|Script|版式草图|Layout sketch)\s*[:：]\s*(\S.*?)\s*$", re.MULTILINE | re.IGNORECASE)
_CODE = re.compile(r"```(?:python|py)[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_ITEM = re.compile(r"^\s*[-*]\s+(.+?)\s*$", re.MULTILINE)


# ========== 解析：总剧本 / 分镜草稿 ==========

def _headings(md: str) -> list[tuple[int, str, int, int]]:
    """全部标题：(级别, 标题, 标题行开头, 标题行结尾)。代码块里以 # 开头的行不算。"""
    masked = _FENCE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), md)
    return [(len(m.group(1)), m.group(2).strip(), m.start(), m.end()) for m in _HEADING.finditer(masked)]


def _starts(title: str, names: tuple[str, ...]) -> bool:
    return title.lower().startswith(tuple(n.lower() for n in names))


def section(md: str, names: tuple[str, ...]) -> str | None:
    """标题以 names 之一开头的第一节的正文（到下一个同级或更高级的标题为止）；没有这一节时返回 None。"""
    heads = _headings(md)
    for i, (level, title, _, end) in enumerate(heads):
        if _starts(title, names):
            stop = next((h[2] for h in heads[i + 1:] if h[0] <= level), len(md))
            return md[end:stop].strip()
    return None


@dataclass
class StripContext:
    """总剧本里和这一条有关的部分。"""

    general: str  # 第一条之前：企画、角色表、场景表、画面总则、节奏表…
    chapter: str  # 这一条所在章节的标题行
    previous: str
    current: str
    following: str


def strip_context(script: str, n: int) -> StripContext | None:
    """按「## 第N条｜标题」（或 Strip N）找出这一条和前后两条；找不到这一条时返回 None。"""
    heads = _headings(script)
    strips: dict[int, tuple[int, str]] = {}  # 第几条 → (标题序号, 这一节的全文)
    for i, (level, title, start, _) in enumerate(heads):
        m = _STRIP_TITLE.match(title)
        if not m:
            continue
        stop = next((h[2] for h in heads[i + 1:] if h[0] <= level), len(script))
        index = int(m.group(1) or m.group(2))
        text = script[start:stop].strip()
        # 同一个编号出现多次（例如节奏表也按条写了标题）时取内容最多的那一节
        if len(text) > len(strips.get(index, (0, ""))[1]):
            strips[index] = (i, text)
    if n not in strips:
        return None
    i, current = strips[n]
    general = script[: min(heads[j][2] for j, _ in strips.values())].strip()
    # 所在章节：前面最近的一个更高级的标题（第一章的标题在 general 里，不用重复）
    chapter = next((script[h[2]:h[3]].strip() for h in reversed(heads[:i]) if h[0] < heads[i][0] and not _STRIP_TITLE.match(h[1])), "")
    if chapter and chapter in general:
        chapter = ""
    return StripContext(general, chapter, strips.get(n - 1, (0, ""))[1], current, strips.get(n + 1, (0, ""))[1])


def draft_meta(draft: str) -> dict[str, str]:
    """分镜草稿标题下面的元数据：{"script": 总剧本路径, "layout": 版式草图路径}（相对项目目录）。"""
    out: dict[str, str] = {}
    for m in _META_LINE.finditer(draft):
        key = "script" if m.group(1).lower() in ("总剧本", "script") else "layout"
        out.setdefault(key, m.group(2))
    return out


def panel_count(directions: str) -> int:
    return sum(1 for _, title, _, _ in _headings(directions) if _PANEL_TITLE.match(title))


def _items(text: str | None) -> list[str]:
    return [m.group(1) for m in _ITEM.finditer(text or "")]


def _after_colon(item: str) -> str:
    return re.split(r"[:：]", item, maxsplit=1)[-1].strip()


def _clip(text: str, limit: int = 160) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ========== draft_strip ==========

@dataclass
class _Sketch:
    png: bytes | None = None
    code: str = ""
    error: str = ""
    unavailable: bool = False  # 沙箱用不了（没装 Deno 等），不用再试


@dataclass
class _Drafter:
    """一次 draft_strip：起草 → 画草图 → 带着草图检查修改。messages 是和起草模型的多轮对话。"""

    ctx: ToolContext
    system: str
    messages: list[dict] = field(default_factory=list)

    def ask(self, parts: list[dict]) -> str:
        self.messages.append({"role": "user", "parts": parts})
        chunks: list[str] = []
        message: dict | None = None
        events = llm.stream_chat("chat", self.system, self.messages, timeout=LLM_TIMEOUT)
        try:
            for event in events:
                if self.ctx.cancel_event is not None and self.ctx.cancel_event.is_set():
                    raise Cancelled()  # 用户停止了：不再等起草模型写完
                if event["type"] == "text":
                    chunks.append(event["text"])
                elif event["type"] == "message":
                    message = event["message"]
        finally:
            close = getattr(events, "close", None)
            if close:
                close()
        reply = "".join(p.get("text", "") for p in (message or {}).get("parts", []) if p["type"] == "text") or "".join(chunks)
        self.messages.append({"role": "model", "parts": [{"type": "text", "text": reply}]})
        return reply

    def draft(self, parts: list[dict]) -> tuple[str, str]:
        """要一份完整草稿（+ 版式代码）；缺「画面指令」一节时提醒一次格式。"""
        draft, code = split_reply(self.ask(parts))
        if not section(draft, DIRECTIONS):
            draft, code2 = split_reply(self.ask([{"type": "text", "text": strip_guide.format_reminder(self.ctx.lang)}]))
            code = code2 or code
        return draft, code

    def sketch(self, code: str) -> _Sketch:
        """运行版式代码；出错时把报错给模型，让它改代码再跑。没装 Deno 等情况下不画草图。"""
        if not code:
            return _Sketch(error=strip_guide.text(self.ctx.lang, "回复里没有版式代码", "the reply had no layout code"))
        error = ""
        for attempt in range(CODE_ATTEMPTS):
            try:
                result = pil_sandbox.run(code, *SKETCH_SIZE)
            except pil_sandbox.SandboxUnavailable as exc:
                return _Sketch(code=code, error=str(exc), unavailable=True)
            if result.ok:
                return _Sketch(png=result.png, code=code)
            error = result.error or "unknown error"
            if attempt + 1 < CODE_ATTEMPTS:
                _, fixed = split_reply(self.ask([{"type": "text", "text": strip_guide.code_error(error, self.ctx.lang)}]))
                code = fixed or code
        return _Sketch(code=code, error=error)


def split_reply(reply: str) -> tuple[str, str]:
    """起草模型的回复 → (草稿正文, 版式代码)：最后一个 python 代码块是代码，其余是草稿。"""
    blocks = list(_CODE.finditer(reply))
    code = blocks[-1].group(1).strip() if blocks else ""
    draft = (reply[: blocks[-1].start()] + reply[blocks[-1].end():]) if blocks else reply
    draft = draft.strip()
    fenced = re.fullmatch(r"```(?:markdown|md)?[ \t]*\n(.*?)\n```", draft, re.DOTALL)
    if fenced:
        draft = fenced.group(1).strip()
    title = re.search(r"^# ", draft, re.MULTILINE)  # 去掉标题前面的客套话
    return (draft[title.start():] if title else draft), code


def _relative(path: Path, project_dir: Path | None) -> str:
    try:
        return str(path.relative_to(project_dir)) if project_dir else str(path)
    except ValueError:
        return str(path)


def _with_meta(draft: str, n: int, script_ref: str, layout_ref: str | None, lang: str) -> str:
    """在标题下面写入元数据（以工具为准，模型自己写的元数据行去掉）。"""
    lines = [line for line in draft.strip().splitlines() if not _META_LINE.match(line)]
    if lines and lines[0].startswith("# "):
        title, body = lines[0], lines[1:]
    else:
        title, body = strip_guide.text(lang, f"# 第{n}条 分镜草稿", f"# Strip {n} draft"), lines
    meta = [strip_guide.text(lang, f"> 总剧本：{script_ref}", f"> Script: {script_ref}")]
    if layout_ref:
        meta.append(strip_guide.text(lang, f"> 版式草图：{layout_ref}", f"> Layout sketch: {layout_ref}"))
    return "\n".join([title, "", *meta, "", *body]).strip() + "\n"


def _find_draft(directory: Path, n: int) -> Path | None:
    for path in sorted(directory.glob("strip_*.md")):
        if re.fullmatch(rf"strip_0*{n}", path.stem):
            return path
    return None


def style_text(project_dir: Path | None, lang: str) -> str:
    """项目的风格设定（style.md；英文界面优先 style_en.md）。"""
    if not project_dir:
        return ""
    for name in (("style_en.md", "style.md") if lang == "en" else ("style.md",)):
        path = project_dir / name
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return ""


def draft_strip(args: dict, ctx: ToolContext) -> dict:
    lang = ctx.lang
    script_path = Path(args["script_path"])
    n = int(args["strip_index"])
    if not script_path.is_file():
        return {"error": f"总剧本不存在: {args['script_path']}"}
    script = script_path.read_text(encoding="utf-8")
    found = strip_context(script, n)
    if found is None:
        return {"error": f"总剧本里找不到第{n}条。每一条要有自己的标题，写成「## 第{n}条｜标题」。"}

    project = ctx.project_dir
    draft_path = Path(args.get("output_path") or (project / DRAFT_DIR / f"strip_{n}.md" if project else DRAFT_DIR / f"strip_{n}.md"))
    draft_path = draft_path.with_suffix(".md")
    if project and not draft_path.resolve().is_relative_to(project.resolve()):
        return {"error": f"output_path 要在项目目录里: {args.get('output_path')}"}
    layout_path = (project / LAYOUT_DIR if project else LAYOUT_DIR) / f"{draft_path.stem}.png"

    neighbors = {}
    for offset in (-1, 1):
        other = _find_draft(draft_path.parent, n + offset) if draft_path.parent.is_dir() else None
        if other and other != draft_path:
            neighbors[offset] = other.read_text(encoding="utf-8")
    existing = draft_path.read_text(encoding="utf-8") if draft_path.is_file() else ""
    names = [str(x) for x in args.get("character_names") or [] if str(x).strip()]

    request = strip_guide.draft_request(
        n=n, found=found, names=names, style=style_text(project, lang),
        visual_rules=section(script, VISUAL_RULES) or "",
        previous_draft=neighbors.get(-1, ""), next_draft=neighbors.get(1, ""),
        existing=existing, notes=str(args.get("notes") or "").strip(), lang=lang,
    )
    try:  # 写法、格式和清单都来自技能（项目可以覆盖），先确认读得到，再调用模型
        system = strip_guide.draft_system(lang, project)
        review_texts = {has: strip_guide.review_request(has_sketch=has, lang=lang, project_dir=project) for has in (True, False)}
    except skills.SkillError as exc:
        return {"error": f"读取分镜草稿的技能出错：{exc}"}
    drafter = _Drafter(ctx, system)
    draft, code = drafter.draft([{"type": "text", "text": request}])
    if not section(draft, DIRECTIONS):
        return {"error": "起草的模型没有按格式写出「画面指令」一节，请再试一次", "reply": _clip(draft, 400)}
    sketch = drafter.sketch(code)

    # 编辑检查：带着草图逐条对照清单，输出改好的完整草稿和代码
    review_parts = [{"type": "text", "text": review_texts[sketch.png is not None]}]
    if sketch.png:
        review_parts.append(image_part(sketch.png, "image/png"))
    revised, revised_code = drafter.draft(review_parts)
    if section(revised, DIRECTIONS):
        draft = revised
        if revised_code and revised_code != sketch.code and not sketch.unavailable:
            redrawn = drafter.sketch(revised_code)
            # 改过的代码跑不通时保留第一版草图（草稿的「版式」一节一般只改了细节）
            sketch = redrawn if redrawn.png or not sketch.png else sketch

    warnings: list[str] = []
    if not section(script, VISUAL_RULES):
        warnings.append(strip_guide.text(
            lang, "总剧本里没有「## 画面总则」一节：生成时只能附上 style.md，建议按 style.md 在总剧本里补上给生图模型看的画面总则",
            "The script has no \"## Visual rules\" section, so generation falls back to style.md; add one to the script",
        ))
    if sketch.error:
        warnings.append(strip_guide.text(lang, f"没有画出版式草图：{_clip(sketch.error, 300)}", f"No layout sketch: {_clip(sketch.error, 300)}"))

    draft_path.parent.mkdir(parents=True, exist_ok=True)
    result: dict = {"draft_path": str(draft_path)}
    layout_ref = None
    if sketch.png:
        layout_path.parent.mkdir(parents=True, exist_ok=True)
        layout_path.write_bytes(sketch.png)
        layout_path.with_suffix(".py").write_text(sketch.code, encoding="utf-8")
        layout_ref = _relative(layout_path, project)
        result.update(output_path=str(layout_path), layout_path=str(layout_path), code_path=str(layout_path.with_suffix(".py")))
    draft_path.write_text(_with_meta(draft, n, _relative(script_path, project), layout_ref, lang), encoding="utf-8")

    concept = _items(section(draft, CONCEPT))
    layout_items = _items(section(draft, LAYOUT))
    changes = [_after_colon(item) for item in _items(section(draft, CHECK)) if _starts(item, ("改动", "Changed"))]
    result.update(
        strip_index=n,
        panels=panel_count(section(draft, DIRECTIONS) or ""),
        summary=_clip(_after_colon(concept[0])) if concept else "",
        layout=_clip(_after_colon(layout_items[0])) if layout_items else "",
        changes=[_clip(c, 120) for c in changes[:6]],
        message=strip_guide.text(
            lang,
            "分镜草稿写好了" + ("，版式草图附在后面" if sketch.png else "") + "。生成这一条时调用 generate_comic_strip，"
            "传 draft_path" + (" 和 layout_path" if sketch.png else "") + "。要改就带上 notes 再调用一次 draft_strip。",
            "The draft is ready" + (" and the layout sketch is attached" if sketch.png else "") + ". To draw this strip, call "
            "generate_comic_strip with draft_path" + (" and layout_path" if sketch.png else "") + ". To change it, call draft_strip again with notes.",
        ),
    )
    if warnings:
        result["warnings"] = warnings
    return result


# ========== review_comic_strip ==========

class StripProblem(BaseModel):
    panel: int = Field(0, description="第几格（按版式草图的编号）；整条的问题填 0")
    area: str = Field("", description="问题在图 2 坐标方格上的位置，如 C4 或 C4:D6；整格或整条的问题留空")
    kind: str = Field("", description="角色 / 表演 / 镜头 / 版式 / 文字 / 连续性 / 其他")
    problem: str = Field(description="成图哪里和分镜草稿不一样，写看得见的东西")
    action: str = Field("", description="修图 / 重画这一格 / 整条重画 / 不用改")
    fix: str = Field("", description="具体怎么改：写成改好以后的样子，可以直接当修图要求用；改字时写出正确的原文")


class StripReview(BaseModel):
    verdict: str = Field(description="pass：可以用；minor：有小问题但能用；redo：建议重画")
    summary: str = Field("", description="一两句总评")
    problems: list[StripProblem] = Field(default_factory=list)


VERDICTS = ("pass", "minor", "redo")
ACTIONS = ("修图", "重画这一格", "整条重画", "不用改")


def _draft_index(draft: str, path: Path) -> int | None:
    """草稿是第几条：先看标题（# 第3条 分镜草稿），再看文件名（strip_3.md）。"""
    title = next((t for level, t, _, _ in _headings(draft) if level == 1), "")
    m = _STRIP_TITLE.search(title)
    if m:
        return int(m.group(1) or m.group(2))
    digits = re.findall(r"\d+", path.stem)
    return int(digits[-1]) if digits else None


def _script_sections(draft: str, draft_path: Path, ctx: ToolContext) -> tuple[str, str]:
    """草稿记录的总剧本里，这一条和上一条的原文（检查时对照情节点和读者须知）。"""
    ref = draft_meta(draft).get("script")
    if not ref:
        return "", ""
    script = Path(ref) if Path(ref).is_absolute() else (ctx.project_dir / ref if ctx.project_dir else Path(ref))
    n = _draft_index(draft, draft_path)
    found = strip_context(script.read_text(encoding="utf-8"), n) if n and script.is_file() else None
    return (found.current, found.previous) if found else ("", "")


def review_comic_strip(args: dict, ctx: ToolContext) -> dict:
    strip = Path(args["strip_path"])
    draft_path = Path(args["draft_path"])
    previous = Path(args["previous_strip_path"]) if args.get("previous_strip_path") else None
    if not strip.is_file():
        return {"error": f"条漫不存在: {args['strip_path']}"}
    if not draft_path.is_file():
        return {"error": f"分镜草稿不存在: {args['draft_path']}"}
    if previous and not previous.is_file():
        return {"error": f"上一条的条漫不存在: {args['previous_strip_path']}"}
    draft = draft_path.read_text(encoding="utf-8")
    directions = section(draft, DIRECTIONS)
    if not directions:
        return {"error": "分镜草稿里没有「画面指令」一节"}
    # 图 1 原图看细节；图 2 叠了坐标方格，说位置用（修图时按同一套方格定位）
    grid = io.BytesIO()
    with Image.open(strip) as img:
        strip_image.draw_grid(img).save(grid, "PNG")
    parts: list[dict] = [
        {"type": "text", "text": strip_guide.text(ctx.lang, "图 1：生成的条漫", "Image 1: the generated strip")}, image_part(strip),
        {"type": "text", "text": strip_guide.text(ctx.lang, "图 2：同一张条漫叠了坐标方格（A–F 列、1–10 行），说位置用",
                                                  "Image 2: the same strip with a coordinate grid (columns A–F, rows 1–10), for locations")},
        image_part(grid.getvalue(), "image/png"),
    ]
    layout = draft_meta(draft).get("layout")
    layout_path = Path(layout) if layout and Path(layout).is_absolute() else (ctx.project_dir / layout if layout and ctx.project_dir else None)
    if layout_path and layout_path.is_file():
        parts += [{"type": "text", "text": strip_guide.text(ctx.lang, "图 3：版式草图", "Image 3: the layout sketch")}, image_part(layout_path)]
    if previous:
        n = sum(1 for p in parts if p["type"] == "image") + 1
        parts += [{"type": "text", "text": strip_guide.text(ctx.lang, f"图 {n}：上一条的成图（检查衔接用）", f"Image {n}: the previous strip (for the transition)")},
                  image_part(previous)]
    current, before = _script_sections(draft, draft_path, ctx)
    parts.append({"type": "text", "text": strip_guide.strip_review_request(
        section(draft, LAYOUT) or "", directions, ctx.lang, script_current=current, script_previous=before, has_previous=previous is not None,
    )})
    try:
        system = strip_guide.strip_review_system(ctx.lang, ctx.project_dir)
    except skills.SkillError as exc:
        return {"error": f"读取检查成图的技能出错：{exc}"}
    review = llm.generate_json("vision", parts, StripReview, system=system, max_retries=2, timeout=240)
    problems = [p.model_dump() for p in review.problems if p.problem.strip()][:12]
    for p in problems:
        p["area"] = p["area"].strip().upper()
        p["action"] = next((a for a in ACTIONS if a in p["action"]), "不用改")  # 没说要修的不修：不要越修越碎
    verdict = review.verdict.strip().lower()
    if verdict not in VERDICTS:
        verdict = "redo" if any(p["action"] == "整条重画" for p in problems) else "minor"
    return {"strip_path": str(strip), "draft_path": str(draft_path), "verdict": verdict, "summary": review.summary, "problems": problems}


register(
    Tool(
        name="draft_strip",
        description=(
            "给总剧本里的一条写分镜草稿（日漫的ネーム）：构思、版式、逐格演出（镜头、构图、动作神态、文字位置）、"
            "自检和最后交给生图模型的「画面指令」，并画好这一条的版式草图。"
            "这个工具单独调用一次模型完成起草、画草图、对照清单检查修改，只把摘要和草图交回来。"
            "草稿存到 output/scripts/strips/strip_N.md，草图存到 output/layouts/。"
            "几条可以在同一次回复里一起调用。要修改已有的草稿，带上 notes 再调用一次。"
        ),
        parameters=obj(
            {
                "script_path": string("总剧本 md 路径（每条要有「## 第N条｜标题」这样的标题）"),
                "strip_index": integer("第几条，从 1 开始"),
                "character_names": array(string("角色名"), "这一条可用的角色名，和之后传给 generate_comic_strip 的 character_names 一致"),
                "notes": string("可选：这次的要求，例如用户想改的地方、上一版草稿或成图的问题"),
                "output_path": string("可选：草稿路径，默认 output/scripts/strips/strip_N.md"),
            },
            ["script_path", "strip_index", "character_names"],
        ),
        run=draft_strip,
        kind="write",
        modes=frozenset({"comic"}),
        model_sees_output=True,
    ),
    Tool(
        name="review_comic_strip",
        description=(
            "对照分镜草稿检查生成的条漫：每一格的人物、动作神态、镜头、版式和文字有没有画对，"
            "返回结论（pass 可以用 / minor 小问题 / redo 建议重画）和问题清单：每个问题有第几格、方格坐标（area）、"
            "修法（action：修图 / 重画这一格 / 整条重画 / 不用改）和具体怎么改（fix）。"
            "会先以第一次看的读者身份冷读，报出读不懂的地方（kind「读不懂」）；传了 previous_strip_path 时一起检查和上一条的衔接。"
            "条漫生成完（check_jobs 拿到结果）、修图之后都调用；接下来怎么做见 strip-fix 技能。"
        ),
        parameters=obj(
            {
                "strip_path": string("生成的条漫图片路径"),
                "draft_path": string("这一条的分镜草稿路径"),
                "previous_strip_path": string("可选：上一条的成图，用来检查和上一条接不接得上"),
            },
            ["strip_path", "draft_path"],
        ),
        run=review_comic_strip,
        kind="read",
        modes=frozenset({"comic"}),
    ),
)
