"""连读：一组草稿 / 一组成图按顺序交给模型，先冷读再对照总剧本的节奏表和读者须知（离线，假的模型）。"""

import pytest
from PIL import Image

from src.providers import llm
from src.web.agent.tools import base, read_through

SCRIPT = """\
# 《门口》总剧本

## 节奏表
- 第1条：铺垫，H；读者须知：小樱放学后一个人留在门口
- 第2条：转折，B；读者须知：她在等的人不会来了

## 第1条｜放学
- 情节点：铃响
- 读者须知：放学了；小樱一个人留在门口。

## 第2条｜门口
- 情节点：等
- 读者须知：
  - 她在等的人不会来了
  - 天黑了
"""


@pytest.fixture
def project(monkeypatch, tmp_path):
    root = tmp_path / "root"
    proj = root / "projects" / "demo"
    (proj / "output" / "scripts" / "strips").mkdir(parents=True)
    (proj / "output" / "panels").mkdir(parents=True)
    (proj / "output" / "scripts" / "story.md").write_text(SCRIPT, encoding="utf-8")
    for n, title in ((1, "放学"), (2, "门口")):
        (proj / "output" / "scripts" / "strips" / f"strip_{n}.md").write_text(
            f"# 第{n}条 分镜草稿｜{title}\n\n> 总剧本：output/scripts/story.md\n\n## 版式\n- 共3格：第{n}条的版式\n\n"
            f"## 画面指令\n### 第1格\n第{n}条第1格的画面。\n", encoding="utf-8")
        Image.new("RGB", (90, 160), "white").save(proj / "output" / "panels" / f"strip_{n}.png")
    monkeypatch.setattr(base, "PROJECT_ROOT", root)
    return proj


def fake_model(monkeypatch, reply: dict) -> list[dict]:
    calls: list[dict] = []

    def generate_json(role, parts, schema, **kwargs):
        calls.append({"role": role, "parts": parts, "system": kwargs.get("system", "")})
        return schema.model_validate(reply)

    monkeypatch.setattr(llm, "generate_json", generate_json)
    return calls


def run(project, **args) -> dict:
    return base.execute(base.get("read_through"), args, base.ToolContext(project_dir=project))


DRAFTS = ["output/scripts/strips/strip_1.md", "output/scripts/strips/strip_2.md"]
STRIPS = ["output/panels/strip_1.png", "output/panels/strip_2.png"]


def test_reading_drafts_through(project, monkeypatch):
    calls = fake_model(monkeypatch, {
        "story": "小樱放学后在门口等人。", "verdict": "Minor",
        "issues": [{"strip": 2, "panel": 1, "kind": "人物", "problem": "不知道她在等谁", "target": "根在草稿", "fix": "改草稿"},
                   {"strip": 1, "problem": "节奏有点平", "target": "也许"}, {"strip": 2, "problem": " "}],
    })
    result = run(project, drafts=DRAFTS, notes="看看人物有没有交代")
    assert result["verdict"] == "minor" and result["story"] == "小樱放学后在门口等人。"
    assert [i["target"] for i in result["issues"]] == ["草稿", "不用改"]  # 说不清根在哪的不修
    assert result["items"] == [{"strip": 1, "draft": str(project / DRAFTS[0])}, {"strip": 2, "draft": str(project / DRAFTS[1])}]

    call = calls[0]
    assert call["role"] == "chat" and "# 连读" in call["system"]  # 草稿是文字，用对话模型；说明来自 read-through 技能
    material = "\n".join(p["text"] for p in call["parts"])
    assert material.index("【第 1 条：第1条 分镜草稿｜放学】") < material.index("【第 2 条：第2条 分镜草稿｜门口】")
    assert "第2条第1格的画面。" in material and "草稿连读" in material
    # 节奏表和每条的读者须知放在最后：先冷读、复述，再对照
    assert material.index("第2条第1格的画面。") < material.index("复述完以后再对照总剧本的节奏表")
    assert "第 1 条：放学了；小樱一个人留在门口。" in material and "第 2 条：她在等的人不会来了；天黑了" in material
    assert "这次特别要看的：看看人物有没有交代" in material


def test_reading_strips_through(project, monkeypatch):
    calls = fake_model(monkeypatch, {"story": "x", "verdict": "pass", "issues": []})
    result = run(project, strips=STRIPS, drafts=DRAFTS)
    assert result["verdict"] == "pass"
    assert result["items"][1] == {"strip": 2, "image": str(project / STRIPS[1]), "draft": str(project / DRAFTS[1])}
    call = calls[0]
    assert call["role"] == "vision"
    images = [p["path"] for p in call["parts"] if p["type"] == "image"]
    assert images == [str(project / s) for s in STRIPS]
    texts = [p["text"] for p in call["parts"] if p["type"] == "text"]
    assert texts[1] == "第 1 条（strip_1.png）" and texts[0].startswith("成图连读")
    assert "只用来判断问题的根在草稿还是成图" in texts[-1]  # 草稿放在图后面，不影响冷读


def test_read_through_reports_bad_requests(project, monkeypatch):
    calls = fake_model(monkeypatch, {"story": "x", "verdict": "pass"})
    assert "至少传一组" in run(project)["error"]
    assert "文件不存在" in run(project, strips=["output/panels/none.png"])["error"]
    assert "最多连读" in run(project, strips=STRIPS * (read_through.MAX_STRIPS // 2 + 1))["error"]
    assert calls == []


def test_later_groups_carry_what_the_reader_already_knows(project, monkeypatch):
    calls = fake_model(monkeypatch, {"story": "x", "verdict": "pass", "issues": []})
    run(project, strips=STRIPS, previously="小樱是转学生，在等她哥哥。")
    texts = [p["text"] for p in calls[0]["parts"] if p["type"] == "text"]
    assert texts[0].startswith("前情") and "小樱是转学生，在等她哥哥。" in texts[0]  # 前情在最前面，图在后面
    assert texts[1].startswith("成图连读")
    assert "previously" in base.get("read_through").description
