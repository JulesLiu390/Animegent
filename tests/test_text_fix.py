"""改字：找到文字框、擦掉旧字、按原文排字（离线，不调用生图模型）。没有中文字体的机器上跳过。"""

import pytest
from PIL import Image, ImageChops, ImageDraw

from src.tools import strip_text
from src.web.agent.tools import base

FONT = strip_text.find_font()
pytestmark = pytest.mark.skipif(FONT is None, reason="没有中文字体")

CAPTION = (40, 40, 320, 130)  # 方形旁白框（含框线）
BALLOON = (60, 300, 300, 420)  # 圆形对白框


def strip() -> Image.Image:
    """浅色画面上一个方形旁白框、一个圆形对白框，框里是旧字。"""
    img = Image.new("RGB", (360, 640), (180, 200, 220))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 350, 630], outline="black", width=4)
    draw.rectangle(CAPTION, fill="white", outline="black", width=3)
    draw.ellipse(BALLOON, fill="white", outline="black", width=3)
    font = strip_text._font(FONT, 24)
    draw.text((60, 58), "跟个字常常", font=font, fill="black")
    draw.text((60, 92), "挤成一个。", font=font, fill="black")
    draw.text((150, 345), "够。", font=font, fill="black")
    return img


@pytest.fixture
def project(monkeypatch, tmp_path):
    root = tmp_path / "root"
    proj = root / "projects" / "demo"
    (proj / "output" / "panels").mkdir(parents=True)
    strip().save(proj / "output" / "panels" / "strip_1.png")
    monkeypatch.setattr(base, "PROJECT_ROOT", root)
    return proj


def run(proj, **args) -> dict:
    return base.execute(base.get("fix_comic_text"), {"image_path": "output/panels/strip_1.png", **args}, base.ToolContext(project_dir=proj))


def test_finds_the_caption_box_and_its_shape():
    img = strip()
    box = strip_text.find_box(img, (20, 20, 340, 160))
    assert box.rectangular and box.fill == (255, 255, 255)
    assert abs(box.rect[0] - 43) <= 2 and abs(box.rect[3] - 127) <= 2  # 框线以内
    assert len(strip_text._bands(box.ink)) == 2  # 两行字
    balloon = strip_text.find_box(img, (40, 280, 330, 440))
    assert not balloon.rectangular
    with pytest.raises(strip_text.TextFixError):
        strip_text.find_box(img, (20, 160, 340, 280))  # 这里没有文字框
    # 方格坐标只框住了框的一部分：往外扩一圈找到和它重叠的那个框
    assert strip_text.find_box(img, (100, 60, 340, 100)).rect == box.rect


def test_reletters_the_boxes_and_leaves_everything_else(project):
    result = run(project, fixes=[{"area": "A1:F3", "text": "两个字常常／挤成一个。"}, {"area": "A5:F7", "text": "够了。"}])
    out_path = project / "output" / "panels" / "strip_1_text1.png"
    assert result["output_path"] == str(out_path) and [f["lines"] for f in result["fixes"]] == [["两个字常常", "挤成一个。"], ["够了。"]]
    assert abs(result["fixes"][0]["font_size"] - 24) <= 3  # 字号照着原来的字
    before, after = strip(), Image.open(out_path).convert("RGB")
    diff = ImageChops.difference(before, after).getbbox()
    assert diff and diff[0] >= CAPTION[0] and diff[3] <= BALLOON[3]  # 只改了框里面
    assert after.getpixel((CAPTION[0] + 1, 80)) == (0, 0, 0)  # 框线还在
    assert after.getpixel((200, 250)) == (180, 200, 220)
    assert ImageChops.difference(before.crop((40, 40, 320, 130)), after.crop((40, 40, 320, 130))).getbbox()  # 旧字换掉了
    assert Image.open(project / "output" / "panels" / "strip_1.png").convert("RGB").getpixel((70, 70)) == before.getpixel((70, 70))  # 原图不动

    # 改字不算修图次数：之后修图还是 fix1；再改字是 text2
    assert run(project, image_path="output/panels/strip_1_text1.png", fixes=[{"area": "A5:F7", "text": "够。"}])["output_path"].endswith("strip_1_text2.png")
    from src.web.agent.tools import fix
    assert fix._rounds(out_path) == 0 and fix.next_output(out_path).name == "strip_1_fix1.png"


def test_reports_what_it_cannot_do(project):
    assert "area" in run(project, fixes=[{"text": "x"}])["error"]
    assert "text" in run(project, fixes=[{"area": "A1:F3"}])["error"]
    assert "找不到文字框" in run(project, fixes=[{"area": "A4:F4", "text": "x"}])["error"]
    assert "fix_comic_strip" in run(project, fixes=[{"area": "A1:F3", "text": "这一句话非常非常长" * 12}])["error"]
    assert "图片不存在" in run(project, image_path="output/panels/none.png", fixes=[{"area": "A1", "text": "x"}])["error"]


def test_does_not_guess_which_box(project):
    # 范围里有两个框：不猜，列出来让 agent 用 nth 指定
    both = run(project, fixes=[{"area": "A1:F7", "text": "够了。"}])
    assert "有 2 个文字框" in both["error"] and "nth" in both["error"]
    picked = run(project, fixes=[{"area": "A1:F7", "nth": 2, "text": "够了。"}])
    assert picked["fixes"][0]["lines"] == ["够了。"] and picked["fixes"][0]["box"][1] > BALLOON[1]
    # 只框住了框的一部分：往外找到那个框；但新的字和原来差得多时，多半是指错了框，不改
    assert run(project, fixes=[{"area": "B1:D2", "text": "两个字常常挤成一个。"}])["fixes"][0]["box"][0] < CAPTION[0] + 5
    assert "可能不是要改的那个框" in run(project, fixes=[{"area": "B1:D2", "text": "嗯"}])["error"]
