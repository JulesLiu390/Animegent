"""分镜草稿：总剧本解析、draft_strip（起草 → 画草图 → 检查修改）、按草稿生成条漫、对照草稿检查成图（离线）。"""

import base64
import io
import threading

import pytest
from PIL import Image

from src.providers import image as image_provider
from src.providers import llm
from src.tools import pil_sandbox
from src.web.agent.tools import base, drafts

SCRIPT = """\
# 《门口》总剧本

## 企画
- 一句话：夏天的晚饭

## 画面总则
- 清淡配色，细腻线条
- 圆形对白框，方形旁白框

## 节奏表
### 第1条：铺垫
### 第2条：推进

# 第一章 门口

## 第01条｜离南京近
- 情节点：县城的街
- 旁白：我们那个县城归安徽管。

# 第二章 晚饭

## 第2条｜门口的晚饭
- 情节点：奶奶端菜，爹爹摇蒲扇
- 旁白：爹爹家是平房。
```python
# 这不是标题
```

## 第3条｜怎么喊
- 情节点：姑姑来了
"""


def draft_reply(changes: str = "待检查", code: str = 'draw.rectangle([20, 20, W - 20, 500], outline="black", width=6)') -> str:
    return f"""好的，下面是草稿。

# 第2条 分镜草稿｜门口的晚饭

## 构思
- 一句话：夏天门口的晚饭，平常又温暖
- 作用：推进

## 版式
- 共3格：上宽下窄，第3格最大
- 第1格：全宽

## 逐格演出
### 第1格｜远景｜交代地点
- 镜头：远景，平视

## 自检
- {changes}

## 画面指令
### 第1格
远景，傍晚的平房门口。旁白框（左上）：「爹爹家是平房。」
### 第2格
中景，奶奶端菜出门。
### 第3格
特写，蚊香的烟。

```python
{code}
```
"""


REVISED = draft_reply("改动：第2格改成中景，和第3格的特写错开", code='draw.rectangle([20, 20, W - 20, 600], outline="black", width=6)')


class FakeStream:
    """替换 llm.stream_chat：依次返回预设的文字回复，记录每次请求（system、messages 的副本）。"""

    def __init__(self, replies, on_call=None):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.on_call = on_call

    def __call__(self, role, system, messages, tools=None, **kwargs):
        self.requests.append({"role": role, "system": system, "messages": [dict(m) for m in messages]})
        if self.on_call:
            self.on_call(len(self.requests))
        reply = self.replies.pop(0)
        yield {"type": "text", "text": reply}
        yield {"type": "message", "message": {"role": "model", "parts": [{"type": "text", "text": reply}]}}


def fake_sandbox(monkeypatch, outcomes=None) -> list[str]:
    """替换 PIL 沙箱：按 outcomes 依次返回（None = 成功，字符串 = 报错，异常 = 抛出），记录运行过的代码。"""
    codes: list[str] = []
    outcomes = list(outcomes or [])

    def run(code, width=900, height=1600, *, timeout=30.0):
        codes.append(code)
        outcome = outcomes.pop(0) if outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, str):
            return pil_sandbox.RunResult(ok=False, error=outcome)
        buf = io.BytesIO()
        Image.new("RGB", (width, height), "white").save(buf, "PNG")
        return pil_sandbox.RunResult(ok=True, png=buf.getvalue(), size=(width, height))

    monkeypatch.setattr(pil_sandbox, "run", run)
    return codes


@pytest.fixture
def project(monkeypatch, tmp_path):
    root = tmp_path / "root"
    proj = root / "projects" / "demo"
    (proj / "output" / "scripts").mkdir(parents=True)
    (proj / "output" / "scripts" / "story.md").write_text(SCRIPT, encoding="utf-8")
    (proj / "style.md").write_text("# 风格\n- 藤井树的画风", encoding="utf-8")
    monkeypatch.setattr(base, "PROJECT_ROOT", root)
    return proj


def run_tool(name: str, args: dict, proj, **ctx_fields) -> dict:
    return base.execute(base.get(name), args, base.ToolContext(project_dir=proj, **ctx_fields))


DRAFT_ARGS = {"script_path": "output/scripts/story.md", "strip_index": 2, "character_names": ["奶奶", "爹爹"]}


# ---- 解析 ----


def test_strip_context_finds_the_strip_and_its_neighbors():
    found = drafts.strip_context(SCRIPT, 2)
    assert found.current.startswith("## 第2条｜门口的晚饭") and "# 这不是标题" in found.current
    assert found.previous.startswith("## 第01条") and found.following.startswith("## 第3条")
    assert found.chapter == "# 第二章 晚饭"  # 第一章的标题已经在 general 里
    assert "## 画面总则" in found.general and "第01条" not in found.general
    assert drafts.strip_context(SCRIPT, 1).chapter == "" and drafts.strip_context(SCRIPT, 1).previous == ""
    assert drafts.strip_context(SCRIPT, 9) is None


def test_sections_stop_at_the_next_heading_of_the_same_level():
    rules = drafts.section(SCRIPT, drafts.VISUAL_RULES)
    assert rules == "- 清淡配色，细腻线条\n- 圆形对白框，方形旁白框"
    draft = drafts.split_reply(draft_reply())[0]
    directions = drafts.section(draft, drafts.DIRECTIONS)
    assert directions.startswith("### 第1格") and directions.endswith("特写，蚊香的烟。")
    assert drafts.panel_count(directions) == 3
    assert drafts.section(draft, ("没有这一节",)) is None


def test_split_reply_separates_the_layout_code():
    draft, code = drafts.split_reply(draft_reply())
    assert draft.startswith("# 第2条 分镜草稿") and "```" not in draft  # 标题前的客套话也去掉了
    assert code == 'draw.rectangle([20, 20, W - 20, 500], outline="black", width=6)'
    assert drafts.split_reply("```markdown\n# 标题\n正文\n```") == ("# 标题\n正文", "")


# ---- draft_strip ----


def test_draft_strip_drafts_sketches_checks_and_saves(project, monkeypatch):
    fake = FakeStream([draft_reply(), REVISED])
    monkeypatch.setattr(llm, "stream_chat", fake)
    codes = fake_sandbox(monkeypatch)
    strips = project / "output" / "scripts" / "strips"
    strips.mkdir(parents=True)
    (strips / "strip_1.md").write_text("# 第1条 分镜草稿\n\n## 版式\n- 共4格：方正四格\n", encoding="utf-8")

    result = run_tool("draft_strip", DRAFT_ARGS, project)

    draft_path = strips / "strip_2.md"
    layout = project / "output" / "layouts" / "strip_2.png"
    assert result["draft_path"] == str(draft_path) and result["output_path"] == result["layout_path"] == str(layout)
    assert layout.is_file() and layout.with_suffix(".py").read_text() == drafts.split_reply(REVISED)[1]
    assert codes == [drafts.split_reply(draft_reply())[1], drafts.split_reply(REVISED)[1]]  # 改过代码就重画
    assert result["panels"] == 3 and result["summary"] == "夏天门口的晚饭，平常又温暖"
    assert result["layout"] == "上宽下窄，第3格最大"
    assert result["changes"] == ["第2格改成中景，和第3格的特写错开"] and "warnings" not in result

    saved = draft_path.read_text()
    assert saved.startswith("# 第2条 分镜草稿｜门口的晚饭\n\n> 总剧本：output/scripts/story.md\n> 版式草图：output/layouts/strip_2.png\n")
    assert "改动：第2格改成中景" in saved and "```" not in saved
    assert drafts.draft_meta(saved) == {"script": "output/scripts/story.md", "layout": "output/layouts/strip_2.png"}

    # 第一次请求：这一条、前后两条、章节、风格、角色名、上一条的草稿，用对话模型
    first = fake.requests[0]
    assert first["role"] == "chat" and "分镜作者" in first["system"] and "门口的晚饭" in first["system"] + str(first["messages"])
    request = first["messages"][0]["parts"][0]["text"]
    for expected in ("## 第2条｜门口的晚饭", "## 第01条｜离南京近", "## 第3条｜怎么喊", "# 第二章 晚饭", "藤井树", "- 奶奶", "方正四格"):
        assert expected in request
    # 第二次请求：同一段对话里接着检查，附上草图
    review = fake.requests[1]["messages"]
    assert [m["role"] for m in review] == ["user", "model", "user"]
    assert "ネーム" in review[2]["parts"][0]["text"] and review[2]["parts"][1]["type"] == "image"


def test_draft_strip_feeds_code_errors_back(project, monkeypatch):
    fixed = 'draw.rectangle([0, 0, 10, 10], outline="black")'
    fake = FakeStream([draft_reply(), f"```python\n{fixed}\n```", draft_reply("改动：无", code=fixed)])
    monkeypatch.setattr(llm, "stream_chat", fake)
    codes = fake_sandbox(monkeypatch, ['  File "<code>", line 1\nNameError: name \'x\' is not defined'])
    result = run_tool("draft_strip", DRAFT_ARGS, project)
    assert codes == [drafts.split_reply(draft_reply())[1], fixed]  # 检查后代码没变，不再重跑
    assert "NameError" in fake.requests[1]["messages"][-1]["parts"][0]["text"]
    assert result["layout_path"] and result["changes"] == ["无"]


def test_draft_strip_without_a_sandbox_still_saves_the_draft(project, monkeypatch):
    monkeypatch.setattr(llm, "stream_chat", FakeStream([draft_reply(), REVISED]))
    fake_sandbox(monkeypatch, [pil_sandbox.SandboxUnavailable("需要安装 Deno")])
    result = run_tool("draft_strip", DRAFT_ARGS, project)
    assert "layout_path" not in result and "output_path" not in result
    assert any("需要安装 Deno" in w for w in result["warnings"])
    assert "版式草图" not in (project / "output" / "scripts" / "strips" / "strip_2.md").read_text()


def test_revising_sends_the_existing_draft_and_notes(project, monkeypatch):
    fake = FakeStream([draft_reply(), REVISED])
    monkeypatch.setattr(llm, "stream_chat", fake)
    fake_sandbox(monkeypatch)
    strips = project / "output" / "scripts" / "strips"
    strips.mkdir(parents=True)
    (strips / "strip_2.md").write_text("# 旧草稿\n\n## 画面指令\n### 第1格\n旧的", encoding="utf-8")
    run_tool("draft_strip", {**DRAFT_ARGS, "notes": "第1格改成俯视"}, project)
    request = fake.requests[0]["messages"][0]["parts"][0]["text"]
    assert "旧的" in request and "第1格改成俯视" in request


def test_draft_strip_reports_problems(project, monkeypatch):
    fake = FakeStream(["随便写写，没有格式", "还是没有格式"])
    monkeypatch.setattr(llm, "stream_chat", fake)
    fake_sandbox(monkeypatch)
    assert run_tool("draft_strip", {**DRAFT_ARGS, "script_path": "output/scripts/none.md"}, project)["error"].startswith("总剧本不存在")
    assert "第9条" in run_tool("draft_strip", {**DRAFT_ARGS, "strip_index": 9}, project)["error"]
    outside = run_tool("draft_strip", {**DRAFT_ARGS, "output_path": str(project.parent / "x.md")}, project)
    assert "项目目录" in outside["error"] and fake.requests == []
    assert "画面指令" in run_tool("draft_strip", DRAFT_ARGS, project)["error"]  # 提醒过一次格式还是不对
    assert len(fake.requests) == 2

    (project / "output" / "scripts" / "plain.md").write_text("# 剧本\n\n## 第1条｜开始\n- 情节点", encoding="utf-8")
    monkeypatch.setattr(llm, "stream_chat", FakeStream([draft_reply(), REVISED]))
    result = run_tool("draft_strip", {**DRAFT_ARGS, "script_path": "output/scripts/plain.md", "strip_index": 1}, project)
    assert any("画面总则" in w for w in result["warnings"])


def test_a_broken_project_skill_stops_before_calling_the_model(project, monkeypatch):
    fake = FakeStream([draft_reply(), REVISED])
    monkeypatch.setattr(llm, "stream_chat", fake)
    fake_sandbox(monkeypatch)
    skill = project / "skills" / "strip-draft"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: 分镜草稿\ndescription: 项目自己的写法\n---\n\n# 写法", encoding="utf-8")
    result = run_tool("draft_strip", DRAFT_ARGS, project)  # 项目的技能缺 template.md
    assert "技能" in result["error"] and "template.md" in result["error"] and fake.requests == []


def test_stopping_interrupts_the_drafting_model(project, monkeypatch):
    stop = threading.Event()
    monkeypatch.setattr(llm, "stream_chat", FakeStream([draft_reply()], on_call=lambda _: stop.set()))
    fake_sandbox(monkeypatch)
    with pytest.raises(base.Cancelled):
        run_tool("draft_strip", DRAFT_ARGS, project, cancel_event=stop)
    assert not (project / "output" / "scripts" / "strips").exists()


# ---- 按草稿生成 ----


def write_draft(project, *, layout: bool = True, directions: bool = True) -> str:
    strips = project / "output" / "scripts" / "strips"
    strips.mkdir(parents=True, exist_ok=True)
    meta = "> 总剧本：output/scripts/story.md\n" + ("> 版式草图：output/layouts/strip_2.png\n" if layout else "")
    body = "## 画面指令\n### 第1格\n远景，门口。\n### 第2格\n特写，蚊香。\n" if directions else "## 构思\n- 一句话\n"
    (strips / "strip_2.md").write_text(f"# 第2条 分镜草稿\n\n{meta}\n## 构思\n- 一句话：晚饭\n\n{body}", encoding="utf-8")
    sketch = project / "output" / "layouts" / "strip_2.png"
    sketch.parent.mkdir(parents=True, exist_ok=True)
    sketch.write_bytes(b"png")
    return "output/scripts/strips/strip_2.md"


def test_comic_strip_draws_from_the_draft(project, monkeypatch):
    captured: dict = {}

    def generate(prompt, refs, **kwargs):
        captured.update(prompt=prompt, refs=list(refs))
        return image_provider.GeneratedImage(b"png", "image/png")

    monkeypatch.setattr(image_provider, "generate", generate)
    character = project / "output" / "stylized" / "a.png"
    character.parent.mkdir(parents=True)
    character.write_bytes(b"png")
    args = {"character_paths": ["output/stylized/a.png"], "character_names": ["奶奶"], "draft_path": write_draft(project),
            "strip_index": 2, "output_path": "output/panels/strip_2.png"}

    result = run_tool("generate_comic_strip", args, project)
    assert result["output_path"] == str(project / "output" / "panels" / "strip_2.png") and result["draft_path"].endswith("strip_2.md")
    layout = project / "output" / "layouts" / "strip_2.png"
    assert captured["refs"] == [str(character), str(layout)]  # 没传 layout_path：用草稿记录的草图
    prompt = captured["prompt"]
    assert "Image 2: PANEL LAYOUT SKETCH" in prompt and "following the panel layout in Image 2" in prompt
    assert "inset panel" in prompt and "capital letter (A, B…)" in prompt  # 草图上的重ねゴマ和跨格人物怎么读
    assert "清淡配色，细腻线条" in prompt  # 总剧本的画面总则
    assert "远景，门口。" in prompt and "一句话：晚饭" not in prompt  # 只给画面指令
    assert "clearly different from every reference character" in prompt and "Do not add any other text" in prompt
    assert "Vary camera angles" not in prompt and "at least 2 panels" not in prompt
    assert "from the visual rules of the master script" in prompt and "藤井树" not in prompt

    # 总剧本没有画面总则：附上项目的 style.md
    story = project / "output" / "scripts" / "story.md"
    story.write_text(SCRIPT.replace("## 画面总则", "## 别的"), encoding="utf-8")
    run_tool("generate_comic_strip", args, project)
    assert "from the project's style guide" in captured["prompt"] and "藤井树的画风" in captured["prompt"]
    story.write_text(SCRIPT, encoding="utf-8")

    # 草稿没有记录草图：按画面指令里的格数
    write_draft(project, layout=False)
    run_tool("generate_comic_strip", args, project)
    assert captured["refs"] == [str(character)] and "with 2 panels" in captured["prompt"]

    write_draft(project, directions=False)
    assert "画面指令" in run_tool("generate_comic_strip", args, project)["error"]
    assert run_tool("generate_comic_strip", {**args, "draft_path": "output/scripts/strips/none.md"}, project)["error"].startswith("分镜草稿不存在")
    assert "draft_path" in run_tool("generate_comic_strip", {**args, "draft_path": ""}, project)["error"]


# ---- 检查成图 ----


def test_review_compares_the_strip_with_the_draft(project, monkeypatch):
    calls: list[dict] = []

    def generate_json(role, parts, schema, **kwargs):
        calls.append({"role": role, "parts": parts, "system": kwargs.get("system", "")})
        return schema.model_validate({
            "verdict": "Redo", "summary": "第1格画成了近景",
            "problems": [
                {"panel": 1, "area": "a1:b2", "kind": "镜头", "problem": "应该是远景", "action": "建议重画这一格", "fix": "远景，门口"},
                {"panel": 2, "kind": "表演", "problem": "手的位置不对", "fix": "左手放在腿上"},
                {"panel": 3, "problem": " "},
            ],
        })

    monkeypatch.setattr(llm, "generate_json", generate_json)
    strip = project / "output" / "panels" / "strip_2.png"
    strip.parent.mkdir(parents=True)
    Image.new("RGB", (90, 160), "white").save(strip)
    args = {"strip_path": "output/panels/strip_2.png", "draft_path": write_draft(project)}

    result = run_tool("review_comic_strip", args, project)
    assert result["verdict"] == "redo" and result["summary"] == "第1格画成了近景"
    assert result["problems"] == [
        {"panel": 1, "area": "A1:B2", "kind": "镜头", "problem": "应该是远景", "action": "重画这一格", "fix": "远景，门口"},
        {"panel": 2, "area": "", "kind": "表演", "problem": "手的位置不对", "action": "不用改", "fix": "左手放在腿上"},  # 没写修法就不修
    ]
    call = calls[0]
    assert call["role"] == "vision" and "编辑" in call["system"] and "方格" in call["system"]
    images = [p for p in call["parts"] if isinstance(p, dict) and p["type"] == "image"]
    assert images[0]["path"] == str(strip) and images[2]["path"] == str(project / "output" / "layouts" / "strip_2.png")
    grid = Image.open(io.BytesIO(base64.b64decode(images[1]["data"])))  # 图 2：叠了坐标方格的同一张图
    assert grid.size == (90, 160) and grid.getpixel((45, 80)) != (255, 255, 255)
    assert "远景，门口。" in call["parts"][-1]["text"] and "方格坐标" in call["parts"][-1]["text"]

    assert run_tool("review_comic_strip", {**args, "strip_path": "output/panels/none.png"}, project)["error"].startswith("条漫不存在")


def test_review_reads_cold_and_checks_the_transition(project, monkeypatch):
    calls: list[dict] = []

    def generate_json(role, parts, schema, **kwargs):
        calls.append({"parts": parts})
        return schema.model_validate({"verdict": "minor", "summary": "姑姑的身份看不出来",
                                      "problems": [{"panel": 2, "kind": "读不懂", "problem": "只露了腿", "action": "修图", "fix": "姑姑坐到饭桌边"}]})

    monkeypatch.setattr(llm, "generate_json", generate_json)
    panels = project / "output" / "panels"
    panels.mkdir(parents=True)
    Image.new("RGB", (90, 160), "white").save(panels / "strip_2.png")
    Image.new("RGB", (90, 160), "gray").save(panels / "strip_1.png")
    args = {"strip_path": "output/panels/strip_2.png", "draft_path": write_draft(project), "previous_strip_path": "output/panels/strip_1.png"}

    result = run_tool("review_comic_strip", args, project)
    assert result["problems"][0]["kind"] == "读不懂"
    parts = calls[0]["parts"]
    images = [p for p in parts if p["type"] == "image"]
    assert images[-1]["path"] == str(panels / "strip_1.png")  # 最后一张是上一条的成图
    labels = [p["text"] for p in parts if p["type"] == "text"]
    assert "图 4：上一条的成图（检查衔接用）" in labels
    request = parts[-1]["text"]
    assert request.startswith("先冷读") and "和上一条的成图" in request
    assert "【总剧本里这一条（对照其中的读者须知）】\n## 第2条｜门口的晚饭" in request  # 草稿记录的总剧本里的这一条
    assert "【总剧本里的上一条】\n## 第01条｜离南京近" in request
    assert "上一条的条漫不存在" in run_tool("review_comic_strip", {**args, "previous_strip_path": "output/panels/none.png"}, project)["error"]
