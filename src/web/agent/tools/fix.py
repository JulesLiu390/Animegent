"""修图：要修的图 + 标好要改的地方的方格图 + 需要的参考（版式草图、截出来的格子、角色图……）一起交给生图模型改。

- fixes 里每一处写第几格（panel）和 / 或方格坐标（area），再写改成什么样（instruction）；改颜色、换东西时可以写 current（现在画成了什么）。
  工具在原图上叠坐标方格、给每一处画编号红框，作为图 2 一起发过去；改颜色这类能用名字说清楚的修改可以不发（marks: false）。
  参考图按需要放，每张都在提示词里标明是什么。
- 只改局部时（默认），只把红框附近、以及和红框连在一起的那片改动贴回原图（框只框住半只手，整只手也会换成新的），
  贴回的范围不超出红框所在的格子，其他像素一个不变。传了版式草图（调格子比例）或者有不限范围的修改时，整张都会变，不贴回。
- 模型返回的整张图另存一份（fixes/xxx_fix1_raw.png）。某一处红框里几乎没变、或者框外的格子有成片变化时提醒：多半是框错了位置。
- 结果另存新文件（xxx_fix1.png），不覆盖原图。花钱：和生成条漫一样在后台执行，「生成前确认」模式下要用户批准。
- 只改字不用这个工具：用 fix_comic_text（text_fix.py）按原文重新排字，不花钱，也不会改出新的错字。
怎么检查、什么时候修、配哪些图，写在 strip-fix 技能里。
"""

from __future__ import annotations

import io
import re
import threading
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

_FIX_SUFFIX = re.compile(r"_(?:fix|text)\d+$")  # 修图、改字的版本都接在原图的名字后面
_ASPECTS = (("9:16", 9 / 16), ("16:9", 16 / 9), ("1:1", 1.0))
MAX_FIXES = 4  # 一次最多修几处
MAX_ROUNDS = 2  # 一条最多修几次（用户明确要求时可以继续）
UNCHANGED = 0.004  # 一处红框里变了的比例低于这个（且不比底噪明显高）就提醒：可能框错了位置


# 同一条的几次修图可以同时在后台跑：输出文件名在开始时就占住，不会写到同一个 xxx_fix1.png，修图次数也不会少算
_names = threading.RLock()
_reserved: set[Path] = set()  # 已经占住、还没写出来的输出文件


def next_output(image: Path, kind: str = "fix") -> Path:
    """xxx.png / xxx_fix1.png → 下一个没用过（也没被占住）的 xxx_<kind>N.png。"""
    stem = _FIX_SUFFIX.sub("", image.stem)
    n = 1
    with _names:
        while (path := image.parent / f"{stem}_{kind}{n}.png").exists() or path.resolve() in _reserved:
            n += 1
    return path


def reserve_output(image: Path, kind: str = "fix", output_path: str | None = None) -> Path:
    """取一个输出文件名并占住，用完调用 release_output。"""
    with _names:
        out = Path(output_path).with_suffix(".png") if output_path else next_output(image, kind)
        _reserved.add(out.resolve())
        return out


def release_output(out: Path) -> None:
    with _names:
        _reserved.discard(out.resolve())


def _rounds(image: Path) -> int:
    """这一条已经修过几次：原图旁边已有的 xxx_fixN.png 个数，加上正在修的（退回旧版再修也算；改字的 xxx_textN.png 不算）。"""
    stem = _FIX_SUFFIX.sub("", image.stem)
    pattern = re.compile(rf"{re.escape(stem)}_fix\d+")
    names = {p.name for p in image.parent.glob(f"{stem}_fix*.png") if pattern.fullmatch(p.stem)}
    with _names:
        folder = image.parent.resolve()
        names |= {p.name for p in _reserved if p.parent == folder and pattern.fullmatch(p.stem)}
    return len(names)


def _aspect(size: tuple[int, int]) -> str | None:
    ratio = size[0] / size[1]
    return next((name for name, value in _ASPECTS if abs(ratio - value) / value < 0.03), None)


def _inside(path: Path, ctx: ToolContext) -> bool:
    return not ctx.project_dir or path.resolve().is_relative_to(ctx.project_dir.resolve())


def _position(rect: strip_image.Rect, size: tuple[int, int]) -> str:
    """不发方格图时，用占整张图的百分比说位置。"""
    w, h = size
    return (f"about {round(100 * rect[0] / w)}–{round(100 * rect[2] / w)}% from the left "
            f"and {round(100 * rect[1] / h)}–{round(100 * rect[3] / h)}% from the top of the strip")


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
    with _names:  # 查次数和占文件名一起做，同时跑的两次修图看得到彼此
        done_rounds = _rounds(image_path)
        if done_rounds >= MAX_ROUNDS and not args.get("confirm_extra_round"):
            return {"error": f"这一条已经修过 {done_rounds} 次了，再修容易越修越碎。先把原图和修过的版本给用户看；"
                             f"用户明确要求继续修时，再传 confirm_extra_round: true"}
        out = Path(args.get("output_path") or next_output(image_path)).with_suffix(".png")
        if not _inside(out, ctx):
            return {"error": f"output_path 要在项目目录里: {args.get('output_path')}"}
        out = reserve_output(image_path, output_path=str(out))
    try:
        return _fix(args, ctx, image_path, fixes, layout, out)
    finally:
        release_output(out)


def _fix(args: dict, ctx: ToolContext, image_path: Path, fixes: list[dict], layout: str, out: Path) -> dict:
    original = Image.open(image_path).convert("RGB")
    panels = strip_image.find_panels(original)
    send_marks = args.get("marks", True) is not False

    # 每一处：定位（格子 / 方格坐标）→ 红框；没写位置的是整张图的修改
    lines: list[str] = []
    boxes: list[tuple[strip_image.Rect, str]] = []
    summary: list[dict] = []
    whole_image = False
    clips: list[list[strip_image.Rect] | None] = []  # 每处贴回时不超出它所在的格子（的内部）
    border = max(4, original.width // 120)
    for i, fix in enumerate(fixes, start=1):
        instruction = str(fix.get("instruction") or "").strip()
        text = str(fix.get("text") or "").strip()
        current = str(fix.get("current") or "").strip()
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
            # 写了第几格就限在这一格；只写了方格坐标时，坐标碰到的几格都可以（坐标常常跨过格缝）
            homes = [panels[int(fix["panel"]) - 1]] if fix.get("panel") else strip_image.panels_in(panels, rect)
            clips.append([strip_image.inset(home, border) for home in homes] or None)
            boxes.append((rect, str(i)))
            if send_marks:
                line += f"Red box {i} ({', '.join(where)}): "
            else:
                spot = f"panel {fix['panel']} (in reading order)" if fix.get("panel") and not fix.get("area") else _position(rect, original.size)
                line += f"In {spot}: "
        else:
            whole_image = True
            line += "Whole strip: "
        if current:
            line += f"Now it shows {current}. Change it to: "
        line += instruction or "Correct the text."
        if text:
            line += f" The text there must read exactly: 「{text}」"
        lines.append(line)
        summary.append({"n": i, "panel": fix.get("panel"), "area": fix.get("area"), "box": list(rect) if rect else None})

    # 参考图：原图、方格标记图（可以不发），然后是版式草图、截出来的格子、其他参考
    work = out.parent / "fixes"
    work.mkdir(parents=True, exist_ok=True)
    marks_path = work / f"{out.stem}_marks.png"
    strip_image.mark(original, boxes).save(marks_path)
    refs = [str(image_path)]
    labels = ["Image 1: the comic strip to fix. Edit THIS image."]
    if send_marks:
        refs.append(str(marks_path))
        labels.append(
            "Image 2: the same strip with a coordinate grid (columns A–F, rows 1–10) and red numbered boxes marking where to fix. "
            "It only shows locations: never draw the grid, the boxes or the numbers."
        )
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
        f"LAYOUT: redraw the panel borders so the panels match Image {refs.index(layout) + 1 if layout else 3} exactly "
        "(shape, size, position and the white gutters). "
        "Move each panel's content into its new frame and re-frame it to fit; keep every panel's content, characters and text.\n\n"
        if layout else ""
    )
    prompt = (
        f"{newline.join(labels)}\n\n"
        f"Fix this comic strip. Change only what the fixes below ask for.\n\n"
        + (f"FIXES:\n{newline.join(lines)}\n\n" if lines else "")
        + layout_rule
        + "KEEP EVERYTHING ELSE THE SAME (everything the fixes above don't mention): the other panels, faces, hair, clothes, "
        "colors, lighting and art style, and every speech balloon, caption and its text. "
        "Characters must look the same as in the strip and in their reference images. Do not add any new text.\n"
        "OUTPUT: the whole strip with the same aspect ratio as Image 1 and the fixes applied."
        + (" Do not draw the grid, the red boxes or the numbers from Image 2." if send_marks else "")
    )
    image = image_provider.generate(prompt, refs, aspect_ratio=_aspect(original.size))
    edited = Image.open(io.BytesIO(image.data)).convert("RGB")
    raw_path = work / f"{out.stem}_raw.png"  # 模型返回的整张图：框错了位置时，看它到底改在了哪里
    edited.save(raw_path)

    # 只改局部时只把红框附近（和连着的那片改动）贴回原图；调版式、整张的修改、或者画幅变了时用整张结果
    warnings: list[str] = []
    composited = False
    keep = args.get("keep_outside", True) is not False and not layout and not whole_image and bool(boxes)
    if keep and strip_image.aspect_close(edited.size, original.size):
        rects = [rect for rect, _ in boxes]
        changes = strip_image.Changes(original, edited)
        result = strip_image.composite(original, edited, rects, clips=clips, changes=changes)
        composited = True
        noise = changes.noise(rects)
        for f in summary:
            if f["box"] is None:
                continue
            f["changed"] = round(changes.fraction(tuple(f["box"])), 4)
            if f["changed"] < max(UNCHANGED, 2 * noise):
                warnings.append(
                    f"第 {f['n']} 处红框里几乎没变（{f['changed']:.1%}）：可能框错了位置，或者模型没改。"
                    f"要改的东西本来就很小（一个按钮、一个字）时可以忽略；否则打开 raw_path（模型返回的整张图）看它改在了哪里，"
                    "按那里重新写 area 再修，或者把 area 放大到整个要改的东西"
                )
        moved = changes.outside(rects, panels)
        if moved:
            warnings.append(
                f"红框以外，第 {'、'.join(map(str, moved))} 格也有成片的变化，这些没有贴回。"
                "如果要改的东西其实在那里，看 raw_path 确认后按那里的位置重新修"
            )
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
        "output_path": str(out), "image_path": str(image_path), "marks_path": str(marks_path), "raw_path": str(raw_path),
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
            "再写改成什么样（instruction）；改颜色、换东西时用 current 写现在画成了什么。area 要框住整个要重画的东西（整只手、整件衣服），不只是露出问题的那一点。"
            "改颜色这类能用名字说清楚的修改传 marks: false，不发方格标记图。"
            "要调格子比例时传 layout_path（版式草图）；前后格要一致时用 reference_panels 把作为标准的格子截出来一起发；"
            "角色图、场景图等放 references（每张写 label 说明是什么，改衣服颜色时附上角色图当颜色标准）。"
            "默认只把红框附近、以及和红框连着的那片改动贴回原图，其他像素不变；某一处几乎没变时会在 warnings 里提醒，raw_path 是模型返回的整张图。"
            "结果另存为 xxx_fix1.png，不覆盖原图。只改字时用 fix_comic_text，不用这个工具。"
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
                            "text": string("改字时：这里应该是的原文（只改字时用 fix_comic_text）"),
                            "current": string("可选：现在画成了什么，例如「浅灰短袖」；改颜色、换东西时写，模型更容易找到要改的地方"),
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
                "marks": boolean("默认 true：发坐标方格 + 红框的标记图指位置；改颜色、换东西这类用名字就说得清楚的修改传 false"),
                "keep_outside": boolean("默认 true：只把红框附近（和连着的那片改动）贴回原图；想让整张一起变时传 false"),
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
