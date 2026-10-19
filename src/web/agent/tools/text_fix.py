"""改字：在成图里找到文字框，擦掉里面的字，按原文用字体重新排字（src/tools/strip_text.py）。

生图模型改字是把字重新画一遍，常常改出新的错字；这里不调用模型，不花钱，字一定和原文一样。
结果另存新文件（xxx_text1.png），不覆盖原图；不算在修图的次数里。
找不到框（字不在白底的框里，比如拟声词、写在画面上的字）或者放不下时报错，这时再用 fix_comic_strip。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.tools import strip_image, strip_text

from .base import Tool, ToolContext, array, integer, obj, register, string
from .fix import release_output, reserve_output

MAX_TEXTS = 8


def fix_comic_text(args: dict, ctx: ToolContext) -> dict:
    image_path = Path(args["image_path"])
    if not image_path.is_file():
        return {"error": f"图片不存在: {args['image_path']}"}
    fixes = [f for f in args.get("fixes") or [] if isinstance(f, dict)]
    if not fixes:
        return {"error": "fixes 里至少写一处：area（框住整个文字框的方格坐标）和 text（正确的原文）"}
    if len(fixes) > MAX_TEXTS:
        return {"error": f"一次最多改 {MAX_TEXTS} 个框"}
    font = strip_text.find_font()
    if font is None:
        return {"error": f"找不到中文字体：把环境变量 {strip_text.FONT_ENV} 设成一个 .ttf / .ttc / .otf 的路径（.ttc 可以写成 路径#序号）"}
    out = reserve_output(image_path, "text", args.get("output_path"))
    try:
        if ctx.project_dir and not out.resolve().is_relative_to(ctx.project_dir.resolve()):
            return {"error": f"output_path 要在项目目录里: {args.get('output_path')}"}
        return _reletter(args, image_path, fixes, font, out)
    finally:
        release_output(out)


def _reletter(args: dict, image_path: Path, fixes: list[dict], font: tuple[str, int], out: Path) -> dict:
    image = Image.open(image_path).convert("RGB")
    panels = strip_image.find_panels(image)
    done: list[dict] = []
    warnings: list[str] = []
    for i, fix in enumerate(fixes, start=1):
        text = str(fix.get("text") or "").strip()
        if not text:
            return {"error": f"第 {i} 处没有写 text（正确的原文）"}
        try:
            if fix.get("area"):
                rect = strip_image.area_rect(str(fix["area"]), image.size)
            elif fix.get("panel"):
                n = int(fix["panel"])
                if not 1 <= n <= len(panels):
                    return {"error": f"第 {i} 处：图里只找到 {len(panels)} 格，没有第 {n} 格；改用方格坐标 area"}
                rect = panels[n - 1]
            else:
                return {"error": f"第 {i} 处没有写位置：area 框住整个文字框（连同框线）"}
            nth = int(fix["nth"]) if fix.get("nth") else None
            box = strip_text.find_box(image, rect, nth=nth)
            # 新的字和原来的字数差得多：多半指错了框（改措辞时可能是故意的，所以框整个在 area 里时只提醒）
            old, new = box.length(), len("".join(strip_text._split(text)))
            mismatch = old > 0 and not 0.5 <= new / old <= 2
            if mismatch and box.nearby:
                return {"error": f"第 {i} 处：area 里没有完整的文字框；旁边和它重叠的框 {list(box.rect)} 里原来大约 {old:.0f} 个字，"
                                 f"和新的 {new} 个字差得多，可能不是要改的那个框。把 area 放大到整个框（连同框线）都在里面再改"}
            if mismatch:
                warnings.append(f"第 {i} 处：框里原来大约 {old:.0f} 个字，新的是 {new} 个字，确认改的是不是这个框")
            info = strip_text.reletter(image, box, text, font)
            if info.get("warning"):
                warnings.append(f"第 {i} 处：{info.pop('warning')}")
        except strip_text.TextFixError as exc:
            return {"error": f"第 {i} 处：{exc}。这一处可以改用 fix_comic_strip（带上 text）修"}
        except ValueError as exc:
            return {"error": f"第 {i} 处：{exc}"}
        done.append({"n": i, "area": fix.get("area"), "panel": fix.get("panel"), "box": list(box.rect), "text": text, **info})

    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    result = {
        "output_path": str(out), "image_path": str(image_path), "fixes": done,
        "message": "已按原文重新排字（没有调用生图模型）。看一眼改的是不是那个框、字号和换行对不对；不对就调整 area 或 text 再改一次。",
    }
    if warnings:
        result["warnings"] = warnings
    return result


register(
    Tool(
        name="fix_comic_text",
        description=(
            "改字：在条漫里找到旁白框、对白框，擦掉框里的字，按 text 用字体重新排字。不调用生图模型、不花钱，字一定和原文一样，"
            "字号、行距、对齐照着原来的字。错字、乱码、缺字、多字都先用它改。"
            "fixes 每一处写 area（方格坐标，框住整个文字框连同框线）和 text（正确的原文，用 ／ 或换行指定分行，不写就自动折行）。"
            "结果另存为 xxx_text1.png，不覆盖原图，不算在修图次数里。字不在白底的框里（拟声词、画面上的字）时会报错，那时用 fix_comic_strip。"
        ),
        parameters=obj(
            {
                "image_path": string("要改字的条漫图片路径"),
                "fixes": array(
                    obj(
                        {
                            "area": string("方格坐标，如 E3:F4，框住整个文字框（连同框线）；只框住一部分也能找到"),
                            "panel": integer("没有 area 时：第几格（在整格里找文字框）"),
                            "nth": integer("可选：area 里有几个文字框时改第几个（从上到下、同一行从左到右）"),
                            "text": string("这个框里应该是的原文；用 ／ 或换行指定分行"),
                        },
                        ["text"],
                    ),
                    "要改的文字框，一个框一条",
                ),
                "output_path": string("可选：输出路径，默认在原图旁边另存 xxx_text1.png"),
            },
            ["image_path", "fixes"],
        ),
        run=fix_comic_text,
        kind="write",
        modes=frozenset({"comic"}),
        model_sees_output=True,
    ),
)
