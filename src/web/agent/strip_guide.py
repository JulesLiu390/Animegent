"""draft_strip（起草、编辑检查）和 review_comic_strip（检查成图）里单独调用的模型看的提示词。

写法、格式和检查清单都在技能里：skills/strip-draft（SKILL.md、template.md、checklist.md）、
skills/panel-layout（分格手法和版式结构）、skills/layout-sketch（草图画法）、skills/strip-review，
项目里的同名技能可以覆盖它们。这里只把技能和这一条的材料拼成请求。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from . import skills

if TYPE_CHECKING:
    from .tools.drafts import StripContext

_ROLE = "你是竖向条漫的分镜作者（日漫里画ネーム的人），按下面的技能文档给一条条漫写分镜草稿，交给生图模型作画。"

_OUTPUT = (
    "## 输出格式\n"
    "严格按下面的格式写完整的草稿，标题和各节顺序都不要改。草稿最后附一个 ```python 代码块，"
    "按「版式」一节和上面的版式草图约定画这一条的版式草图（只画格框、编号和虚线，不画人物和文字）。草稿前后不要有别的话。\n"
)


def text(lang: str, zh: str, en: str) -> str:
    return en if lang == "en" else zh


def draft_system(lang: str, project_dir: Path | None) -> str:
    """起草模型的系统提示词：分镜草稿、分格、版式草图三个技能 + 输出格式（模板）。缺技能时抛 SkillError。"""
    draft = skills.get("strip-draft", project_dir)
    panels = skills.get("panel-layout", project_dir)
    layout = skills.get("layout-sketch", project_dir)
    name = "template.en.md" if lang == "en" and "template.en.md" in draft.resources() else "template.md"
    language = "\nWrite the whole draft in English with exactly these English headings.\n" if lang == "en" else "\n草稿用中文写。\n"
    return f"{_ROLE}\n\n{draft.body()}\n\n{panels.body()}\n\n{layout.body()}\n\n{_OUTPUT}\n{draft.resource(name).strip()}\n{language}"


def _block(title: str, body: str) -> str:
    return f"【{title}】\n{body.strip()}\n\n" if body.strip() else ""


def draft_request(*, n: int, found: StripContext, names: list[str], style: str, visual_rules: str,
                  previous_draft: str, next_draft: str, existing: str, notes: str, lang: str) -> str:
    """起草的第一条消息：这一条要用到的全部材料。"""
    cast = "\n".join(f"- {name}" for name in names) or "（没有指定，按总剧本的角色表）"
    out = f"请给第{n}条写分镜草稿。\n\n"
    out += _block("可用角色（参考图会和画面指令一起交给生图模型；草稿里只用这些名字称呼他们，其他人都是路人）", cast)
    out += _block("项目风格设定 style.md", style)
    out += _block("总剧本：第一条之前的部分（企画、角色表、场景表、画面总则、节奏表）", found.general)
    if not visual_rules:
        out += "（总剧本里没有「画面总则」一节，生成时会附上 style.md：画面指令里同样不用写画风，只写这一格特有的东西。）\n\n"
    out += _block("这一条所在的章节", found.chapter)
    out += _block(f"上一条（第{n - 1}条）", found.previous)
    out += _block(f"这一条（第{n}条）：要写分镜草稿的就是这一条", found.current)
    out += _block(f"下一条（第{n + 1}条）", found.following)
    out += _block("上一条已经写好的分镜草稿（接住它的最后一格，版式不要和它一样）", previous_draft)
    out += _block("下一条已经写好的分镜草稿（版式不要和它一样）", next_draft)
    if existing:
        out += _block("这一条现有的分镜草稿（在它的基础上修改，没提到的地方尽量保留）", existing)
    out += _block("这次的要求", notes)
    out += "按系统说明里的格式，写出完整的分镜草稿，再附上版式草图的 python 代码。"
    if lang == "en":
        out += "\nWrite the draft in English."
    return out


def review_request(*, has_sketch: bool, lang: str, project_dir: Path | None) -> str:
    """第二遍：编辑检查。带着草图逐条对照 strip-draft 技能的清单，输出改好的完整草稿和代码。"""
    checklist = skills.get("strip-draft", project_dir).resource("checklist.md").strip()
    sketch = "版式草图画好了，附在后面。" if has_sketch else "这次没能画出版式草图，只检查草稿。"
    out = (
        f"{sketch}现在换成编辑的身份，像检查ネーム一样，逐条对照下面的清单检查这份草稿"
        f"{'和草图' if has_sketch else ''}。只挑真正的问题，不要为了改而改。\n\n"
        f"{checklist}\n\n"
        "检查完，输出修改后的完整草稿（格式和之前一样），「自检」一节写上查出的问题和改动；"
        "最后附上完整的版式代码（```python 代码块，没改也要完整给出）。草稿前后不要有别的话。"
    )
    if lang == "en":
        out += "\nKeep the draft in English with the English headings."
    return out


def format_reminder(lang: str) -> str:
    return text(
        lang,
        "格式不对：草稿必须按系统说明里的格式写，包含「## 画面指令」一节，每格一个「### 第N格」小节，最后附 ```python 代码块。请输出完整的草稿和代码。",
        "Wrong format: the draft must follow the format in the instructions, including a \"## Panel directions\" section "
        "with one \"### Panel N\" subsection per panel, followed by a ```python code block. Output the full draft and code.",
    )


def code_error(error: str, lang: str) -> str:
    return text(
        lang,
        f"版式代码运行出错：\n{error}\n\n只回复改好的完整代码（一个 ```python 代码块），不用重复草稿。",
        f"The layout code failed:\n{error}\n\nReply with only the fixed, complete code (one ```python block); don't repeat the draft.",
    )


# ========== 检查成图 ==========

def strip_review_system(lang: str, project_dir: Path | None) -> str:
    """检查成图的模型的系统提示词：strip-review 技能。缺技能时抛 SkillError。"""
    body = skills.get("strip-review", project_dir).body()
    return body + ("\n\nWrite summary, problem and fix in English." if lang == "en" else "\n\n用中文写总评、问题和 fix。")


def strip_review_request(layout: str, directions: str, lang: str, *, script_current: str = "", script_previous: str = "",
                         has_previous: bool = False) -> str:
    cold = (
        "先冷读：不看下面的分镜草稿，只看图 1" + ("和上一条的成图" if has_previous else "")
        + "，以第一次看的读者身份判断读不读得懂，再对照「总剧本里这一条」的读者须知。然后才对照草稿检查画得对不对。\n\n"
    )
    return (
        cold
        + _block("总剧本里的上一条", script_previous)
        + _block("总剧本里这一条（对照其中的读者须知）", script_current)
        + _block("分镜草稿的「版式」", layout)
        + _block("分镜草稿的「画面指令」", directions)
        + "对照上面的草稿检查图 1 的条漫。图 2 是叠了坐标方格的同一张图，说位置时用它的方格坐标；有图 3 时，图 3 是这一条的版式草图。"
        "每个问题写出第几格、方格坐标、修法和具体怎么改。"
    )
