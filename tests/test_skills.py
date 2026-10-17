"""技能：内置技能、项目技能覆盖、frontmatter、参考文件的路径安全、系统提示词里的技能目录、读取技能的工具、
分镜草稿和检查成图的提示词从技能里取（离线；示例代码那一项要 Deno）。"""

import pytest

from src.tools import pil_sandbox
from src.web.agent import prompts, skills, strip_guide
from src.web.agent.tools import base, for_mode

BUILTIN = {"master-script", "strip-draft", "panel-layout", "layout-sketch", "strip-review", "strip-fix", "read-through", "storyboard-video"}


def write_skill(root, skill_id, *, name="测试技能", description="测试用", scopes="", body="# 正文\n内容", files=None):
    d = root / skill_id
    d.mkdir(parents=True)
    scope_line = f"scopes: {scopes}\n" if scopes else ""
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n{scope_line}---\n\n{body}\n", encoding="utf-8")
    for rel, content in (files or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(content, encoding="utf-8")
    return d


# ---- 内置技能 ----


def test_builtin_skills_are_valid():
    found = skills.discover(None)
    assert BUILTIN <= set(found)
    assert all(s.source == "builtin" and s.body().strip() for s in found.values())
    draft = found["strip-draft"]
    assert {"template.md", "template.en.md", "checklist.md", "sources.md"} <= set(draft.resources())
    # 草稿模板里的这些标题由程序解析
    for heading in ("## 构思", "## 版式", "## 逐格演出", "## 自检", "## 画面指令", "### 第1格"):
        assert heading in draft.resource("template.md")
    for heading in ("## Concept", "## Layout", "## Self-check", "## Panel directions", "### Panel 1"):
        assert heading in draft.resource("template.en.md")
    assert {s.id for s in skills.available(None, "comic")} == BUILTIN - {"storyboard-video"}
    # 让第一次看的读者跟得上：这些规则写在技能里，被删掉时测试会发现
    for skill_id, heading in [("master-script", "## 改编原文的规则"), ("master-script", "## 时间线交错"),
                              ("strip-draft", "## 交代：让第一次看的读者跟得上"), ("panel-layout", "## 场景转换与回想"),
                              ("strip-review", "## 第一步：冷读"), ("strip-fix", "## 读不懂的问题先找根")]:
        assert heading in found[skill_id].body(), (skill_id, heading)
    assert "## 第一次看的读者" in draft.resource("checklist.md")
    assert [s.id for s in skills.available(None, "storyboard")] == ["storyboard-video"]


def test_layout_sketch_example_runs_in_the_sandbox():
    if not pil_sandbox.find_deno():
        pytest.skip("没有安装 Deno")
    try:
        pil_sandbox.ensure_pyodide()
    except pil_sandbox.SandboxUnavailable as exc:
        pytest.skip(str(exc))
    blocks = [b.split("```", 1)[0] for b in skills.get("layout-sketch", None).body().split("```python\n")[1:]]
    helpers, examples = blocks[0], blocks[1:]
    assert len(examples) == 4  # A 叙述型、B L 形、C 断ち切り + 重ねゴマ、D コマまたぎ
    for code in examples:
        result = pil_sandbox.run(helpers + "\n" + code)
        assert result.ok, result.error


# ---- frontmatter ----


def test_frontmatter():
    meta, body = skills.parse('---\nname: "总剧本"\ndescription: 写总剧本前读\nversion: 1.2.0\nscopes:\n  - comic\n  - storyboard\n---\n\n# 正文\n')
    assert meta == {"name": "总剧本", "description": "写总剧本前读", "version": "1.2.0", "scopes": ("comic", "storyboard")}
    assert body == "# 正文"
    assert skills.parse("---\nname: a\ndescription: b\nscopes: [comic]\n---\nx")[0]["scopes"] == ("comic",)
    assert skills.parse("---\nname: a\ndescription: b\n---\nx")[0]["scopes"] == ()  # 不写 = 所有模式
    assert skills.parse("---\nname: a\ndescription: >\n  第一行\n  第二行\n---\nx")[0]["description"] == "第一行 第二行"
    for bad, message in [
        ("# 没有 frontmatter", "frontmatter"),
        ("---\nname: a\n", "结束"),
        ("---\nname: a\n---\n", "description"),
        ("---\nname: a\ndescription: b\nscopes: [有 空格]\n---\n", "scopes"),
        ("---\n这一行没有冒号\n---\n", "看不懂"),
    ]:
        with pytest.raises(skills.SkillError, match=message):
            skills.parse(bad)


# ---- 内置 + 项目 ----


def test_project_skills_override_builtin_ones(tmp_path, monkeypatch):
    builtin = tmp_path / "builtin"
    monkeypatch.setattr(skills, "BUILTIN_DIR", builtin)
    write_skill(builtin, "strip-draft", description="内置的")
    write_skill(builtin, "video-only", scopes="[storyboard]")
    write_skill(builtin, "Bad_Name")  # 目录名不对：跳过
    project = tmp_path / "proj"
    write_skill(project / "skills", "strip-draft", description="项目的")
    write_skill(project / "skills", "extra")

    found = skills.discover(project)
    assert list(found) == ["extra", "strip-draft", "video-only"]
    assert found["strip-draft"].source == "project" and found["strip-draft"].description == "项目的"
    assert skills.discover(None)["strip-draft"].description == "内置的"
    # 项目技能格式不对：退回内置的
    (project / "skills" / "strip-draft" / "SKILL.md").write_text("没有 frontmatter", encoding="utf-8")
    assert skills.discover(project)["strip-draft"].source == "builtin"
    # 按创作模式过滤
    assert [s.id for s in skills.available(project, "comic")] == ["extra", "strip-draft"]
    with pytest.raises(skills.SkillError, match="可以用的技能：extra、strip-draft"):
        skills.get("video-only", project, "comic")


def test_resources_stay_inside_the_skill(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "BUILTIN_DIR", tmp_path / "builtin")
    d = write_skill(tmp_path / "builtin", "demo", files={"refs/guide.md": "指南", ".hidden": "x"})
    (tmp_path / "secret.txt").write_text("secret")
    (d / "link.md").symlink_to(tmp_path / "secret.txt")
    (d / "image.bin").write_bytes(b"\xff\xfe\x00")
    (d / "big.md").write_text("x" * (skills.MAX_RESOURCE_BYTES + 1))
    skill = skills.get("demo", None)

    assert skill.resources() == ["big.md", "image.bin", "refs/guide.md"]  # 隐藏文件和符号链接不列出
    assert skill.resource("refs/guide.md") == "指南"
    for bad in ["../secret.txt", "/etc/passwd", "refs/../../secret.txt", "refs\\guide.md", "", "link.md", "missing.md"]:
        with pytest.raises(skills.SkillError):
            skill.resource(bad)
    with pytest.raises(skills.SkillError, match="UTF-8"):
        skill.resource("image.bin")
    with pytest.raises(skills.SkillError, match="太大"):
        skill.resource("big.md")


# ---- 系统提示词 / 工具 ----


def test_system_prompt_lists_the_skills_of_the_mode(tmp_path):
    proj = tmp_path / "projects" / "demo"
    write_skill(proj / "skills", "my-style", name="我的画风", description="这个项目的画风要点。\n  画角色前读。")  # 缩进续行
    system = prompts.build_system_prompt(mode="comic", interaction="confirm", lang="zh", project_dir=proj,
                                         tools=for_mode("comic"), unfinished_jobs=[])
    assert "可用技能" in system and "- master-script（总剧本）：" in system
    assert "- my-style（我的画风，项目自定义）：这个项目的画风要点。 画角色前读。" in system
    assert "storyboard-video" not in system and "skill_load 读 master-script" in system


def test_skill_tools_read_skills_and_their_files(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "PROJECT_ROOT", tmp_path)
    proj = tmp_path / "projects" / "demo"
    write_skill(proj / "skills", "my-style", body="# 画风\n- 线条要细", files={"examples/ok.md": "好例子"})
    ctx = base.ToolContext(project_dir=proj, mode="comic")

    loaded = base.execute(base.get("skill_load"), {"skill_id": "my-style"}, ctx)
    assert loaded["source"] == "project" and loaded["resources"] == ["examples/ok.md"]
    assert "--- BEGIN SKILL.md ---\n# 画风\n- 线条要细\n--- END SKILL.md ---" in loaded["content"]
    assert "description:" not in loaded["content"]  # 只给正文
    resource = base.execute(base.get("skill_read_resource"), {"skill_id": "my-style", "path": "examples/ok.md"}, ctx)
    assert resource["path"] == "examples/ok.md" and "好例子" in resource["content"]
    assert "不能有" in base.execute(base.get("skill_read_resource"), {"skill_id": "my-style", "path": "../x"}, ctx)["error"]
    # 条漫模式下看不到分镜模式的技能
    assert "没有这个技能" in base.execute(base.get("skill_load"), {"skill_id": "storyboard-video"}, ctx)["error"]
    storyboard = base.execute(base.get("skill_load"), {"skill_id": "storyboard-video"}, base.ToolContext(project_dir=proj, mode="storyboard"))
    assert "分镜脚本" in storyboard["content"]


def test_strip_draft_prompts_come_from_the_skills(tmp_path):
    proj = tmp_path / "proj"
    write_skill(proj / "skills", "strip-draft", body="# 项目自己的分镜写法\n- 每格都要有猫",
                files={"template.md": "# 第N条 分镜草稿\n## 画面指令\n### 第1格", "checklist.md": "1. 有猫吗？"})
    system = strip_guide.draft_system("zh", proj)
    assert "每格都要有猫" in system and "# 版式草图的画法" in system  # 版式草图技能还是内置的
    assert "# 分格与版式（コマ割り）" in system and system.index("每格都要有猫") < system.index("# 分格与版式") < system.index("# 版式草图的画法")
    assert system.index("每格都要有猫") < system.index("## 输出格式") < system.index("### 第1格")
    assert "有猫吗？" in strip_guide.review_request(has_sketch=True, lang="zh", project_dir=proj)
    assert strip_guide.strip_review_system("zh", proj).startswith("# 检查成图")
    # 内置的英文模板
    assert "## Panel directions" in strip_guide.draft_system("en", None)

    (proj / "skills" / "strip-draft" / "checklist.md").unlink()
    with pytest.raises(skills.SkillError, match="checklist.md"):
        strip_guide.review_request(has_sketch=True, lang="zh", project_dir=proj)
