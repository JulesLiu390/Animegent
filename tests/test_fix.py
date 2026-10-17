"""修图：找格子、坐标方格、只贴回红框附近，以及 fix_comic_strip 怎么把原图、标记图和参考图交给生图模型（离线，假的生图）。"""

import io

import pytest
from PIL import Image, ImageDraw

from src.providers import image as image_provider
from src.tools import strip_image
from src.web.agent.tools import base

COLORS = [(200, 80, 80), (80, 200, 80), (80, 80, 200), (200, 200, 80)]


def strip(size=(360, 640)) -> Image.Image:
    """白底黑框的条漫：第一行两格并排；第二行一格，格子里面有一条白带（不是格缝）；第三行一格。"""
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    for i, (x0, y0, x1, y1) in enumerate([(10, 10, 175, 200), (185, 10, 350, 200), (10, 215, 350, 430), (10, 445, 350, 630)]):
        draw.rectangle([x0, y0, x1, y1], fill=COLORS[i], outline="black", width=4)
    draw.rectangle([14, 300, 346, 320], fill="white")
    return img


# ---- 图片处理 ----


def test_panels_are_found_in_reading_order():
    rects = strip_image.find_panels(strip())
    assert len(rects) == 4
    assert [r[1] < 15 for r in rects] == [True, True, False, False] and rects[0][0] < rects[1][0]
    assert rects[2][1] < 300 < rects[2][3]  # 格子里面的白带没有把格子切开


def test_grid_areas():
    size = (360, 640)
    assert strip_image.area_rect("A1", size) == (0, 0, 60, 64)
    assert strip_image.area_rect("c4:d6", size) == (120, 192, 240, 384)
    assert strip_image.area_rect("D6-C4", size) == (120, 192, 240, 384)
    for bad in ["G1", "A11", "A0", "", "A1:B2:C3", "4C"]:
        with pytest.raises(ValueError):
            strip_image.area_rect(bad, size)


def test_composite_only_touches_the_boxes():
    original = Image.new("RGB", (400, 400), "white")
    edited = Image.new("RGB", (200, 200), "black")  # 尺寸不同时先缩放
    out = strip_image.composite(original, edited, [(150, 150, 250, 250)])
    assert out.size == (400, 400)
    assert out.getpixel((200, 200)) == (0, 0, 0) and out.getpixel((20, 20)) == (255, 255, 255)
    assert out.getpixel((150 - 40, 200)) == (255, 255, 255)
    # 限制在所在的格子里：框外放大的那一圈不越过格子
    clipped = strip_image.composite(original, edited, [(150, 150, 250, 250)], clips=[(140, 140, 240, 240)])
    assert clipped.getpixel((200, 200)) == (0, 0, 0) and clipped.getpixel((245, 200)) == (255, 255, 255)


# ---- fix_comic_strip ----


@pytest.fixture
def project(monkeypatch, tmp_path):
    root = tmp_path / "root"
    proj = root / "projects" / "demo"
    (proj / "output" / "panels").mkdir(parents=True)
    (proj / "output" / "stylized").mkdir(parents=True)
    strip().save(proj / "output" / "panels" / "strip_1.png")
    Image.new("RGB", (90, 160), "pink").save(proj / "output" / "stylized" / "aunt.png")
    monkeypatch.setattr(base, "PROJECT_ROOT", root)
    return proj


def fake_generate(monkeypatch, size=(360, 640), color=(255, 0, 0)) -> list[dict]:
    calls: list[dict] = []

    def generate(prompt, refs, **kwargs):
        calls.append({"prompt": prompt, "refs": [str(r) for r in refs], **kwargs})
        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, "PNG")
        return image_provider.GeneratedImage(buf.getvalue(), "image/png")

    monkeypatch.setattr(image_provider, "generate", generate)
    return calls


def fix(proj, **args) -> dict:
    return base.execute(base.get("fix_comic_strip"), {"image_path": "output/panels/strip_1.png", **args}, base.ToolContext(project_dir=proj))


def test_fix_sends_the_strip_marks_and_references(project, monkeypatch):
    calls = fake_generate(monkeypatch)
    panels = project / "output" / "panels"
    result = fix(
        project,
        fixes=[{"panel": 1, "instruction": "左手平放在大腿上"}, {"area": "c6:d7", "text": "我是小炮子子。", "instruction": "这个旁白框改字"}],
        reference_panels=[{"panel": 2, "label": "桌面物件以这一格为准"}],
        references=[{"path": "output/stylized/aunt.png", "label": "角色 姑姑"}],
    )
    assert result["output_path"] == str(panels / "strip_1_fix1.png") and result["composited"] is True
    assert result["panels_found"] == 4 and [f["n"] for f in result["fixes"]] == [1, 2]

    call = calls[0]
    marks = panels / "fixes" / "strip_1_fix1_marks.png"
    assert call["refs"] == [str(panels / "strip_1.png"), str(marks), str(panels / "fixes" / "strip_1_fix1_panel2.png"),
                            str(project / "output" / "stylized" / "aunt.png")]
    assert call["aspect_ratio"] == "9:16"
    prompt = call["prompt"]
    for expected in ("Image 1: the comic strip to fix", "Image 2: the same strip with a coordinate grid",
                     "Image 3: panel 2 of this strip, for reference. 桌面物件以这一格为准", "Image 4: 角色 姑姑",
                     "1. Red box 1 (panel 1): 左手平放在大腿上",
                     "2. Red box 2 (grid cells C6:D7): 这个旁白框改字 The text there must read exactly: 「我是小炮子子。」",
                     "KEEP EVERYTHING ELSE THE SAME"):
        assert expected in prompt
    assert "LAYOUT" not in prompt
    assert Image.open(marks).getpixel((15, 15)) != Image.open(panels / "strip_1.png").getpixel((15, 15))  # 画了红框

    # 只贴回红框附近：第 1 格变红，第 4 格不动
    out = Image.open(result["output_path"])
    assert out.getpixel((90, 100)) == (255, 0, 0)
    assert out.getpixel((180, 600)) == COLORS[3]
    assert out.getpixel((180, 437)) == (255, 255, 255)  # 2 号框伸进了格缝，但贴回只在第 3 格里面
    assert out.getpixel((12, 100)) == (0, 0, 0)  # 第 1 格的格框保持原样
    assert Image.open(panels / "strip_1.png").getpixel((90, 100)) == COLORS[0]  # 原图不覆盖

    # 第二次修另存 fix2（在 fix1 上接着修也算这一条的第二次）
    again = base.execute(base.get("fix_comic_strip"), {"image_path": "output/panels/strip_1_fix1.png", "fixes": [{"panel": 1, "instruction": "x"}]},
                         base.ToolContext(project_dir=project))
    assert again["output_path"].endswith("strip_1_fix2.png")
    # 修满两次就先停下来：退回原图再修也一样；用户明确要求时才继续
    third = fix(project, fixes=[{"panel": 3, "instruction": "x"}])
    assert "已经修过 2 次" in third["error"] and len(calls) == 2
    assert fix(project, fixes=[{"panel": 3, "instruction": "x"}], confirm_extra_round=True)["output_path"].endswith("strip_1_fix3.png")


def test_layout_fix_uses_the_sketch_and_keeps_the_whole_result(project, monkeypatch):
    calls = fake_generate(monkeypatch)
    sketch = project / "output" / "layouts" / "strip_1.png"
    sketch.parent.mkdir(parents=True)
    Image.new("RGB", (900, 1600), "white").save(sketch)
    result = fix(project, layout_path="output/layouts/strip_1.png")
    assert calls[0]["refs"][2] == str(sketch) and "Image 3: PANEL LAYOUT SKETCH" in calls[0]["prompt"]
    assert "LAYOUT: redraw the panel borders so the panels match Image 3" in calls[0]["prompt"]
    assert result["composited"] is False and Image.open(result["output_path"]).getpixel((180, 600)) == (255, 0, 0)


def test_whole_strip_changes_and_aspect_changes_are_not_pasted_back(project, monkeypatch):
    fake_generate(monkeypatch)
    assert fix(project, fixes=[{"instruction": "整体调暗一点"}])["composited"] is False
    fake_generate(monkeypatch, size=(512, 512))
    result = fix(project, fixes=[{"panel": 1, "instruction": "x"}])
    assert result["composited"] is False and "画幅" in result["warnings"][0]


def test_fix_reports_bad_requests(project, monkeypatch):
    calls = fake_generate(monkeypatch)
    assert "至少写一处" in fix(project)["error"]
    assert "没有第 9 格" in fix(project, fixes=[{"panel": 9, "instruction": "x"}])["error"]
    assert "方格坐标" in fix(project, fixes=[{"area": "Z9", "instruction": "x"}])["error"]
    assert "instruction" in fix(project, fixes=[{"panel": 1}])["error"]
    assert "参考图不存在" in fix(project, fixes=[{"panel": 1, "instruction": "x"}], references=[{"path": "none.png"}])["error"]
    assert "项目目录" in fix(project, fixes=[{"panel": 1, "instruction": "x"}], output_path=str(project.parent / "x.png"))["error"]
    assert "图片不存在" in fix(project, image_path="output/panels/none.png", fixes=[{"panel": 1, "instruction": "x"}])["error"]
    assert "一次最多修 4 处" in fix(project, fixes=[{"panel": 1, "instruction": "x"}] * 5)["error"]
    assert calls == []
