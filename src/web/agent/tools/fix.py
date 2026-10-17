"""修图：要修的图 + 标好要改的地方的方格图 + 需要的参考（版式草图、截出来的格子、角色图……）一起交给生图模型改。

- fixes 里每一处写第几格（panel）和 / 或方格坐标（area），改字时写 text，再写改成什么样（instruction）。
  工具在原图上叠坐标方格、给每一处画编号红框，作为图 2 一起发过去；参考图按需要放，每张都在提示词里标明是什么。
- 只改局部时（默认），生成后只把红框附近的部分贴回原图，其他像素一个不变，别的格的字和脸不会被碰到。
  传了版式草图（调格子比例）或者有不限范围的修改时，整张都会变，不贴回。
- 结果另存新文件（xxx_fix1.png），不覆盖原图。花钱：和生成条漫一样在后台执行，「生成前确认」模式下要用户批准。
怎么检查、什么时候修、配哪些图，写在 strip-fix 技能里。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image

from src.providers import image as image_provider
from src.tools import strip_image

from .base import (
    Tool,
    ToolContext,
    array,
    boolean,
    integer,
    obj,
    register,
    resolve_path,
    string,
)

_FIX_SUFFIX = re.compile(r"_fix\d+$")
_ASPECTS = (("9:16", 9 / 16), ("16:9", 16 / 9), ("1:1", 1.0))
MAX_FIXES = 4  # 一次最多修几处
MAX_ROUNDS = 2  # 一条最多修几次（用户明确要求时可以继续）


def _next_output(image: Path) -> Path:
    stem = _FIX_SUFFIX.sub("", image.stem)
    n = 1
    while (image.parent / f"{stem}_fix{n}.png").exists():
        n += 1
    return image.parent / f"{stem}_fix{n}.png"


def _rounds(image: Path) -> int:
    """这一条已经修过几次：原图旁边已有的 xxx_fixN.png 个数（退回旧版再修也算）。"""
    stem = _FIX_SUFFIX.sub("", image.stem)
    return sum(1 for p in image.parent.glob(f"{stem}_fix*.png") if re.fullmatch(rf"{re.escape(stem)}_fix\d+", p.stem))


def _aspect(size: tuple[int, int]) -> str | None:
    ratio = size[0] / size[1]
    return next((name for name, value in _ASPECTS if abs(ratio - value) / value < 0.03), None)


def _inside(path: Path, ctx: ToolContext) -> bool:
    return not ctx.project_dir or path.resolve().is_relative_to(ctx.project_dir.resolve())


def fix_comic_strip(args: dict, ctx: ToolContext) -> dict:
    image_path = Path(args["image_path"])
    if not image_path.is_file():
        return {"error": f"图片不存在: {args['image_path']}"}
    fixes = [f for f in args.get("fixes") or [] if isinstance(f, dict)]
    layout = args.get("layout_path") or ""
    if not fixes and not layout:
        return {"error": "fixes 里至少写一处要修的地方（第几格 / 方格坐标 + 改成什么样），或者传 layout_path 按版式草图调整格子"}
    if layout and not Path(layout).is_file():
        return {"error": f"版式草图不存在: {layout}"}
    # 不要越修越碎：一次修得太多、一条修了太多次都先停下来
    if len(fixes) > MAX_FIXES:
        return {"error": f"一次最多修 {MAX_FIXES} 处。先修会让读者读错、连续性断掉、情绪落空或者字错的地方，其余的不用改（见 strip-fix 技能）"}
    done_rounds = _rounds(image_path)
    if done_rounds >= MAX_ROUNDS and not args.get("confirm_extra_round"):
        return {"error": f"这一条已经修过 {done_rounds} 次了，再修容易越修越碎。先把原图和修过的版本给用户看；"
                         f"用户明确要求继续修时，再传 confirm_extra_round: true"}
    out = Path(args.get("output_path") or _next_output(image_path)).with_suffix(".png")
    if not _inside(out, ctx):
        return {"error": f"output_path 要在项目目录里: {args.get('output_path')}"}

    original = Image.open(image_path).convert("RGB")
    panels = strip_image.find_panels(original)

    # 每一处：定位（格子 / 方格坐标）→ 红框；没写位置的是整张图的修改
    lines: list[str] = []
    boxes: list[tuple[strip_image.Rect, str]] = []
    summary: list[dict] = []
    whole_image = False
    clips: list[strip_image.Rect | None] = []  # 每处贴回时不超出它所在那一格的内部
    border = max(4, original.width // 120)
    for i, fix in enumerate(fixes, start=1):
        instruction = str(fix.get("instruction") or "").strip()
        text = str(fix.get("text") or "").strip()
        if not instruction and not text:
            return {"error": f"第 {i} 处没有写要改成什么样（instruction）"}
        rect: strip_image.Rect | None = None
        where: list[str] = []
        if fix.get("panel"):
            n = int(fix["panel"])
            if not 1 <= n <= len(panels):
                return {"error": f"第 {i} 处：图里只找到 {len(panels)} 格，没有第 {n} 格；可以改用方格坐标 area 指位置"}
            rect = panels[n - 1]
            where.append(f"panel {n}")
        if fix.get("area"):
            try:
                rect = strip_image.area_rect(str(fix["area"]), original.size)
            except ValueError as exc:
                return {"error": f"第 {i} 处：{exc}"}
            where.append(f"grid cells {str(fix['area']).upper()}")
        line = f"{i}. "
        if rect:
            home = panels[int(fix["panel"]) - 1] if fix.get("panel") else strip_image.panel_at(panels, rect)
            clips.append(strip_image.inset(home, border) if home else None)
            boxes.append((rect, str(i)))
            line += f"Red box {i} ({', '.join(where)}): "
        else:
            whole_image = True
            line += "Whole strip: "
        line += instruction or "Correct the text."
        if text:
            line += f" The text there must read exactly: 「{text}」"
        lines.append(line)
        summary.append({"n": i, "panel": fix.get("panel"), "area": fix.get("area"), "box": list(rect) if rect else None})

    # 参考图：原图、方格标记图，然后是版式草图、截出来的格子、其他参考
    work = out.parent / "fixes"
    work.mkdir(parents=True, exist_ok=True)
    marks_path = work / f"{out.stem}_marks.png"
    strip_image.mark(original, boxes).save(marks_path)
    refs = [str(image_path), str(marks_path)]
    labels = [
        "Image 1: the comic strip to fix. Edit THIS image.",
        (
            "Image 2: the same strip with a coordinate grid (columns A–F, rows 1–10) and red numbered boxes marking where to fix. "
            "It only shows locations: never draw the grid, the boxes or the numbers."
        ),
    ]
    if layout:
        refs.append(layout)
        labels.append(f"Image {len(refs)}: PANEL LAYOUT SKETCH. The panel borders must match it.")
    for item in args.get("reference_panels") or []:
        item = item if isinstance(item, dict) else {"panel": item}
        n = int(item.get("panel") or 0)
        if not 1 <= n <= len(panels):
            return {"error": f"reference_panels：图里只找到 {len(panels)} 格，没有第 {n} 格"}
        crop = work / f"{out.stem}_panel{n}.png"
        original.crop(panels[n - 1]).save(crop)
        refs.append(str(crop))
        labels.append(f"Image {len(refs)}: panel {n} of this strip, for reference. {str(item.get('label') or '').strip()}".strip())
    for item in args.get("references") or []:
        item = item if isinstance(item, dict) else {"path": item}
        path = resolve_path(str(item.get("path") or ""), ctx.project_dir)
        if not Path(path).is_file():
            return {"error": f"参考图不存在: {item.get('path')}"}
        refs.append(path)
        labels.append(f"Image {len(refs)}: {str(item.get('label') or '').strip() or Path(path).name}")

    newline = "\n"
    layout_rule = (
        "LAYOUT: redraw the panel borders so the panels match Image 3 exactly (shape, size, position and the white gutters). "
        "Move each panel's content into its new frame and re-frame it to fit; keep every panel's content, characters and text.\n\n"
        if layout else ""
    )
    prompt = (
        f"{newline.join(labels)}\n\n"
        f"Fix this comic strip. Change only what the fixes below ask for.\n\n"
        + (f"FIXES:\n{newline.join(lines)}\n\n" if lines else "")
        + layout_rule
        + "KEEP EVERYTHING ELSE THE SAME: the other panels, faces, hair, clothes, colors, lighting and art style, "
        "and every speech balloon, caption and its text. Characters must look the same as in the strip and in their reference images. "
        "Do not add any new text.\n"
        "OUTPUT: the whole strip with the same aspect ratio as Image 1 and the fixes applied. "
        "Do not draw the grid, the red boxes or the numbers from Image 2."
    )
    image = image_provider.generate(prompt, refs, aspect_ratio=_aspect(original.size))
    edited = Image.open(io.BytesIO(image.data)).convert("RGB")

    # 只改局部时只把红框附近贴回原图；调版式、整张的修改、或者画幅变了时用整张结果
    warnings: list[str] = []
    composited = False
    keep = args.get("keep_outside", True) is not False and not layout and not whole_image and bool(boxes)
    if keep and strip_image.aspect_close(edited.size, original.size):
        result = strip_image.composite(original, edited, [rect for rect, _ in boxes], clips=clips)
        composited = True
    else:
        result = edited
        if keep:
            warnings.append(
                f"生图模型返回的画幅（{edited.width}×{edited.height}）和原图（{original.width}×{original.height}）不一样，"
                "没法只贴回红框里的部分，整张图都可能有变化"
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    result.save(out)
    done: dict = {
        "output_path": str(out), "image_path": str(image_path), "marks_path": str(marks_path),
        "composited": composited, "panels_found": len(panels), "fixes": summary,
    }
    if layout:
        done["layout_path"] = layout
    if warnings:
        done["warnings"] = warnings
    if image.text:
        done["text"] = image.text
    return done


register(
    Tool(
        name="fix_comic_strip",
        description=(
            "修图：把要修的条漫、标好要改的地方的方格图和需要的参考图一起交给生图模型改，不用整条重画。"
            "fixes 里每一处写第几格（panel）和 / 或方格坐标（area，6 列 A–F × 10 行 1–10 盖住整张图，如 C4 或 C4:D6），"
            "改字时写 text（正确的原文），再写改成什么样（instruction）。"
            "要调格子比例时传 layout_path（版式草图）；前后格要一致时用 reference_panels 把作为标准的格子截出来一起发；"
            "角色图、场景图等放 references（每张写 label 说明是什么）。"
            "默认只把红框附近的改动贴回原图，其他像素不变。结果另存为 xxx_fix1.png，不覆盖原图。"
            f"一次最多修 {MAX_FIXES} 处，一条最多修 {MAX_ROUNDS} 次：只修会让读者读错、连续性断掉、情绪落空或者字错的地方。怎么用见 strip-fix 技能。"
        ),
        parameters=obj(
            {
                "image_path": string("要修的条漫图片路径"),
                "fixes": array(
                    obj(
                        {
                            "panel": integer("第几格（从上到下、同一行从左到右）；不确定时用 area"),
                            "area": string("方格坐标，如 C4 或 C4:D6（和 review_comic_strip 给的一样）"),
                            "text": string("改字时：这里应该是的原文"),
                            "instruction": string("改成什么样，只写这一处"),
                        },
                        ["instruction"],
                    ),
                    "要修的地方，一处一条；同一张图的几处一起修",
                ),
                "layout_path": string("可选：版式草图。传了就按草图调整格子的形状和比例（整张都会变）"),
                "reference_panels": array(
                    obj({"panel": integer("第几格"), "label": string("说明，例如：桌面物件的位置以这一格为准")}, ["panel"]),
                    "可选：从这张图里截出来作为参考的格子",
                ),
                "references": array(
                    obj({"path": string("图片路径"), "label": string("说明，例如：角色 姑姑")}, ["path"]),
                    "可选：其他参考图（角色图、场景图、别的条漫……）",
                ),
                "keep_outside": boolean("默认 true：只把红框附近的改动贴回原图；想让整张一起变时传 false"),
                "confirm_extra_round": boolean("这一条已经修过两次、用户明确要求继续修时才传 true"),
                "output_path": string("可选：输出路径，默认在原图旁边另存 xxx_fix1.png"),
            },
            ["image_path"],
        ),
        run=fix_comic_strip,
        kind="generate",
        modes=frozenset({"comic"}),
    ),
)
