"""改字（只用 PIL，不调用生图模型）：在成图里找到文字框，擦掉框里的字，按原文用字体重新排字。

生图模型改字是把字重新画一遍，常常改出新的错字。旁白框、对白框是白底黑字，直接排字最稳。
- 找框：在给的范围里找一块被框线围住的白色区域（不碰到范围的边）。框里的字是这块白色里的「洞」，一起算作框的内部。
- 字号、行距、颜色、对齐照着原来的字估：横排的字一行一条墨迹带，带的高度约等于字号。
  方框（旁白框）左对齐，圆框（对白框）居中。新字放不下时缩小字号，还放不下就报错。
"""

from __future__ import annotations

import itertools
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageStat

Rect = tuple[int, int, int, int]

FONT_ENV = "ANIMEGENT_CJK_FONT"  # 指向一个 .ttf / .ttc / .otf（.ttc 可以写成 路径#序号）
FONT_CANDIDATES = (  # (路径, .ttc 里的序号)：中等粗细的黑体，和生图模型常画的旁白字接近
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Medium.ttc", 2),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc", 2),
    ("C:/Windows/Fonts/msyhbd.ttc", 0),
    ("C:/Windows/Fonts/msyh.ttc", 0),
)
_WHITE = 225  # 灰度 ≥ 这个值算框里的白底
_INK = 110  # 灰度 ≤ 这个值算字的墨迹（量字号、取字的颜色）
_MIN_STROKES = 2  # 字至少有这么多块分开的墨迹（「够。」是两块；白纸上的一根辫子是一块）
_OUTLINE = 160  # 框线外圈的灰度上限（框线边上有抗锯齿的灰）
BREAKS = ("\n", "／")  # 原文里的换行：草稿的画面指令用「／」分行


class TextFixError(ValueError):
    """这一处没法直接排字（找不到框、放不下……），message 说明原因。"""


def find_font() -> tuple[str, int] | None:
    configured = os.environ.get(FONT_ENV, "").strip()
    if configured:
        path, _, index = configured.partition("#")
        return path, int(index or 0)
    for path, index in FONT_CANDIDATES:
        if Path(path).is_file():
            return path, index
    return None


def _font(spec: tuple[str, int], size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(spec[0], size, index=spec[1])
    except OSError:
        return ImageFont.truetype(spec[0], size)


@dataclass
class Box:
    rect: Rect  # 框内部（含字）的外接矩形，整张图的坐标
    interior: Image.Image  # rect 大小的蒙版：框内部（白底 + 字）
    ink: Image.Image  # rect 大小的蒙版：原来的字
    rectangular: bool  # 方框（旁白框）还是圆框（对白框）
    fill: tuple[int, int, int]
    color: tuple[int, int, int]
    nearby: bool = False  # area 里没有完整的框，这是往外扩了一圈找到的、和 area 重叠的框

    def length(self) -> float:
        """原来的字大约有几个（按每行墨迹的宽和字高估）。"""
        bands = _bands(self.ink)
        if not bands:
            return 0.0
        em = median([b - a for a, b in bands]) / 0.88
        return sum(_ink_width(self.ink, band) for band in bands) / em + 0.3 * len(bands)


def _components(white: Image.Image, limit: int = 250) -> list[tuple[int, Rect, tuple[int, int]]]:
    """白色连通块：(像素数, 外接矩形, 块里的一个点)，在一张标号图上用 floodfill 逐块标出来。"""
    work = white.copy()
    w, h = work.size
    found: list[tuple[int, Rect, tuple[int, int]]] = []
    label = 1
    step = max(2, min(w, h) // 80)
    for y in range(0, h, step):
        for x in range(0, w, step):
            if work.getpixel((x, y)) != 255:
                continue
            ImageDraw.floodfill(work, (x, y), label)
            only = work.point(lambda v, n=label: 255 if v == n else 0)
            found.append((only.histogram()[255], only.getbbox(), (x, y)))
            label += 1
            if label >= limit:
                return found
    return found


def find_box(image: Image.Image, area: Rect, *, nth: int | None = None) -> Box:
    """area 里被框线围住、里面有字的白色区域，就是要改的文字框。

    - 方格坐标很粗，框常常跨过方格线：area 里没有完整的框时，往外扩一圈再找，取和 area 重叠最多的那个框。
    - area 里有几个框时：nth 指定第几个（从上到下、同一行从左到右）；没给 nth 时报错，不猜。
    """
    rgb = image.convert("RGB")
    boxes = sorted(_boxes_in(rgb, area), key=lambda b: (b.rect[1] // 20, b.rect[0]))
    if nth is not None:
        if not 1 <= nth <= len(boxes):
            raise TextFixError(f"area 里有 {len(boxes)} 个文字框，没有第 {nth} 个")
        return boxes[nth - 1]
    if len(boxes) > 1:
        listed = "；".join(f"第 {i} 个 {list(b.rect)}，大约 {b.length():.0f} 个字" for i, b in enumerate(boxes, start=1))
        raise TextFixError(f"area 里有 {len(boxes)} 个文字框（{listed}）：用 nth 指定改第几个（从上到下、同一行从左到右），或者把 area 缩小到只框住那一个")
    if boxes:
        return boxes[0]
    grow = max(area[2] - area[0], area[3] - area[1]) // 2 + 20
    wider = (max(0, area[0] - grow), max(0, area[1] - grow), min(rgb.width, area[2] + grow), min(rgb.height, area[3] + grow))

    def overlap(b: Box) -> int:
        x0, y0 = max(b.rect[0], area[0]), max(b.rect[1], area[1])
        x1, y1 = min(b.rect[2], area[2]), min(b.rect[3], area[3])
        return max(0, x1 - x0) * max(0, y1 - y0)

    # 框得有一大块落在 area 里，才算是 area 指的那个框
    touching = [b for b in _boxes_in(rgb, wider) if overlap(b) >= 0.25 * (b.rect[2] - b.rect[0]) * (b.rect[3] - b.rect[1])]
    if not touching:
        raise TextFixError("范围里找不到文字框（白底、有框线、框里有字）：确认 area 指的是旁白框或对白框，并把整个框都框进去")
    best = max(touching, key=overlap)
    best.nearby = True
    return best


def _boxes_in(rgb: Image.Image, area: Rect) -> list[Box]:
    """area 里所有完整的文字框（不碰到 area 的边）。"""
    crop = rgb.crop(area)
    white = crop.convert("L").point(lambda v: 255 if v >= _WHITE else 0)
    # 先去掉细碎的白点、白线再找块，少数大块里才有文字框
    opened = white.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    w, h = crop.size
    candidates = sorted(((size, box, seed) for size, box, seed in _components(opened)
                         if box and box[0] > 0 and box[1] > 0 and box[2] < w and box[3] < h and size >= 400), reverse=True)
    return [box for _, bbox, seed in candidates if (box := _box(rgb, area, white, bbox, seed))]


def _box(rgb: Image.Image, area: Rect, white: Image.Image, found: Rect, point: tuple[int, int]) -> Box | None:
    """一块白色区域（外接矩形 found，point 是块里的一点）→ 文字框；不像文字框（没有字、四周没有框线）时返回 None。"""
    w, h = white.size
    bx0, by0, bx1, by1 = max(0, found[0] - 3), max(0, found[1] - 3), min(w, found[2] + 3), min(h, found[3] + 3)
    local = white.crop((bx0, by0, bx1, by1))
    # 回到没去碎点的白底：从块里那一点出发，把整块白底标出来
    region = local.copy()
    ImageDraw.floodfill(region, (point[0] - bx0, point[1] - by0), 128)
    background = region.point(lambda v: 255 if v == 128 else 0)
    # 框外：从四周灌进来、连着框线的所有非白底；剩下的（白底 + 被白底围住的字）是框的内部
    padded = Image.new("L", (local.width + 2, local.height + 2), 0)
    padded.paste(background, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 64)
    interior = padded.crop((1, 1, local.width + 1, local.height + 1)).point(lambda v: 0 if v == 64 else 255)
    bbox = interior.getbbox()
    if not bbox:
        return None
    rect = (area[0] + bx0 + bbox[0], area[1] + by0 + bbox[1], area[0] + bx0 + bbox[2], area[1] + by0 + bbox[3])
    interior = interior.crop(bbox)
    background = background.crop(bbox)
    # 四周一圈要大多是深色的框线（框线粗细不一，量 2–4 像素宽的几圈，取最像的）
    around = rgb.crop((rect[0] - 4, rect[1] - 4, rect[2] + 4, rect[3] + 4)).convert("L").point(lambda v: 255 if v <= _OUTLINE else 0)
    inner = _place(interior, around.size)
    best = 0.0
    for amount in (2, 3, 4):
        edge = ImageChops.subtract(_grow(interior, amount, around.size), inner)
        total = edge.histogram()[255]
        best = max(best, ImageChops.multiply(edge, around).histogram()[255] / total if total else 0.0)
    if best < 0.6:
        return None
    inside = rgb.crop(rect)
    dark = inside.convert("L").point(lambda v: 255 if v <= _INK else 0)
    ink = ImageChops.multiply(dark, interior)
    holes = ImageChops.subtract(interior, background)
    area_px = max(1, interior.histogram()[255])
    bands = _bands(ink)
    if not 0.01 <= ink.histogram()[255] / area_px <= 0.5 or not bands:
        return None
    # 字是细笔画：按字高的三成腐蚀以后基本不剩；剩下一大块的是画（白纸上的辫子、碗里的东西），不是字
    k = max(5, round(median([b - a for a, b in bands]) * 0.3)) | 1
    if ink.filter(ImageFilter.MinFilter(k)).histogram()[255] > 0.15 * ink.histogram()[255]:
        return None
    # 字由很多分开的笔画组成；只有一两块墨迹的是画（白纸上的一根辫子），不是字
    if _strokes(ink) < _MIN_STROKES:
        return None
    filled = area_px / max(1, interior.width * interior.height)

    def typical(mask: Image.Image, default: tuple[int, int, int]) -> tuple[int, int, int]:
        if not mask.getbbox():
            return default
        return tuple(round(v) for v in ImageStat.Stat(inside, mask).median)  # type: ignore[return-value]

    return Box(rect, interior, ink, filled >= 0.92, typical(ImageChops.subtract(interior, holes), (255, 255, 255)), typical(ink, (25, 25, 25)))


def _strokes(ink: Image.Image) -> int:
    return sum(1 for size, _, _ in _components(ink, limit=12) if size >= 4)


def _place(mask: Image.Image, size: tuple[int, int], offset: int = 4) -> Image.Image:
    out = Image.new("L", size, 0)
    out.paste(mask, (offset, offset))
    return out


def _grow(mask: Image.Image, amount: int, size: tuple[int, int]) -> Image.Image:
    return _place(mask, size).filter(ImageFilter.MaxFilter(2 * amount + 1))


def _bands(ink: Image.Image) -> list[tuple[int, int]]:
    """原来的字一行一条墨迹带：(上, 下)。"""
    rows = ink.resize((1, ink.height), Image.Resampling.BOX)
    getter = getattr(rows, "get_flattened_data", None) or rows.getdata
    on = [v > 0 for v in getter()]
    bands: list[tuple[int, int]] = []
    start = None
    gap = 0
    for y, flag in enumerate([*on, False, False, False]):
        if flag:
            start = y if start is None else start
            gap = 0
        elif start is not None:
            gap += 1
            if gap > 2:
                if y - gap + 1 - start >= 4:
                    bands.append((start, y - gap + 1))
                start, gap = None, 0
    return bands


_CLOSING = "，。、！？；：」』）…,.!?;:)"


def _ink_width(ink: Image.Image, band: tuple[int, int]) -> int:
    bbox = ink.crop((0, band[0], ink.width, band[1])).getbbox()
    return bbox[2] - bbox[0] if bbox else 0


def _phrases(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """按标点分成短语再装行：只在标点后面断开；一个短语本身比一行长时退回逐字折行。"""
    lines: list[str] = []
    for part in _split(text):
        line = ""
        for phrase in re.findall(rf"[^{_CLOSING}]+[{_CLOSING}]*|[{_CLOSING}]+", part):
            if line and font.getlength(line + phrase) > width:
                lines.append(line)
                line = ""
            if font.getlength(phrase) > width:
                lines.extend(_wrap(line + phrase, font, width)[:-1])
                line = _wrap(line + phrase, font, width)[-1]
            else:
                line += phrase
        lines.append(line)
    return [line for line in lines if line]


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """按宽度折行：尽量在标点后面断开（后半行至少有一半），标点不放在行首。"""
    lines: list[str] = []
    for part in _split(text):
        line = ""
        for ch in part:
            if line and font.getlength(line + ch) > width and ch not in _CLOSING:
                # 先找标点后面；没有标点时找中文和字母、数字交界的地方（「等拿到PR／以后再说」）
                cut = max((i + 1 for i, c in enumerate(line) if c in _CLOSING), default=0)
                if not cut:
                    cut = max((i + 1 for i in range(len(line) - 1) if line[i].isascii() != line[i + 1].isascii()), default=0)
                if cut >= len(line) / 2 and cut < len(line):
                    lines.append(line[:cut])
                    line = line[cut:] + ch
                else:
                    lines.append(line)
                    line = ch
            else:
                line += ch
        lines.append(line)
    return lines


def _units(line: str) -> float:
    """一行字墨迹的宽，以字为单位：行尾的标点只占小半个字。"""
    return len(line) - (0.65 if line and line[-1] in _CLOSING else 0)


def _fit(lines: list[str], widths: list[int], size: int, tolerance: float = 0.12) -> float | None:
    """lines 排成原来那几行时每个字占多宽（像素）；行的长短比例对不上，或者和字号差得多（新的字比原来多或少了不少）时返回 None。"""
    units = [_units(line) for line in lines]
    if len(units) != len(widths) or not sum(widths):
        return None
    scale = sum(widths) / max(0.1, sum(units))
    error = sum(abs(u * scale - w) for u, w in zip(units, widths)) / sum(widths)
    # 只有一行时比例总是对得上，只能看字宽：差一个字，短句的字宽就会差两成
    low, high = (0.88, 1.1) if len(units) == 1 else (0.85, 1.15)
    return scale if error <= tolerance and low * size <= scale <= high * size else None


def _match_breaks(chars: str, widths: list[int], size: int) -> tuple[list[str], float] | None:
    """把 chars 断成 len(widths) 行，让每行的长短和原来那几行最接近；对不上时返回 None。返回 (行, 每个字的宽)。"""
    n, count = len(chars), len(widths)
    if n < count or count > 4 or n > 60:
        return None
    best: tuple[float, list[str], float] | None = None
    for cuts in itertools.combinations(range(1, n), count - 1):
        lines = [chars[a:b] for a, b in zip((0, *cuts), (*cuts, n))]
        if any(line[0] in _CLOSING for line in lines[1:]):
            continue
        scale = _fit(lines, widths, size)
        if scale is None:
            continue
        error = sum(abs(_units(line) * scale - w) for line, w in zip(lines, widths))
        if best is None or error < best[0]:
            best = (error, lines, scale)
    return (best[1], best[2]) if best else None


def _split(text: str) -> list[str]:
    for mark in BREAKS:
        text = text.replace(mark, "\n")
    return [line.strip() for line in text.split("\n") if line.strip()]


def reletter(image: Image.Image, box: Box, text: str, font_spec: tuple[str, int]) -> dict:
    """在 image 上（原地）擦掉 box 里的字，排上 text。返回用的字号和行。"""
    if not _split(text):
        raise TextFixError("text 是空的")
    x0, y0, x1, y1 = box.rect
    bw, bh = x1 - x0, y1 - y0
    bands = _bands(box.ink)
    ink_box = box.ink.getbbox() or (bw // 8, bh // 4, bw - bw // 8, bh - bh // 4)
    band_h = median([b - a for a, b in bands]) if bands else max(12, bh // 4)
    probe = _font(font_spec, 100).getbbox(_split(text)[0])  # 这个字体的字在字号 100 时墨迹有多高
    size = max(10, round(band_h * 100 / max(1, probe[3] - probe[1])))
    pitch_ratio = (median([b[0] - a[0] for a, b in zip(bands, bands[1:])]) / size) if len(bands) > 1 else 1.4
    pitch_ratio = min(max(pitch_ratio, 1.15), 1.8)
    left = ink_box[0]
    cx, cy = (ink_box[0] + ink_box[2]) / 2, (ink_box[1] + ink_box[3]) / 2
    if not box.rectangular:  # 圆框：以框最宽的那一段为中心，尾巴不会把字拉偏
        rows = box.interior.resize((1, bh), Image.Resampling.BOX)
        getter = getattr(rows, "get_flattened_data", None) or rows.getdata
        spans = list(getter())
        widest = max(spans)
        middle = [y for y, v in enumerate(spans) if v >= 0.95 * widest]
        cy = (middle[0] + middle[-1]) / 2
        line_mask = box.interior.crop((0, round(cy), bw, round(cy) + 1)).getbbox()
        if line_mask:
            cx = (line_mask[0] + line_mask[2]) / 2
    original_width = max((_ink_width(box.ink, band) for band in bands), default=ink_box[2] - ink_box[0])
    start_size = size
    explicit = any(mark in text for mark in BREAKS)
    # 新的字和原来差不多长（改错字最常见）：照原来每一行的长短断行，字号也按原来的字宽定，排出来和原来一样
    widths = [_ink_width(box.ink, band) for band in bands]
    given = _split(text)
    matched = (given, _fit(given, widths, size)) if explicit else _match_breaks("".join(given), widths, size) if bands else None
    if matched and matched[1]:
        text, explicit = "／".join(matched[0]), True
        size = max(10, int(matched[1]))  # 中文字一个字宽一个字号；取整往下，宁可比原来窄一点
    smallest = max(8, round(size * 0.75))  # 比原来小太多就不像同一条漫画里的字了
    rooms: dict[int, Image.Image] = {}

    def room(font_size: int) -> Image.Image:
        """字能排的地方：框的内部再往里缩一圈，字号越大留得越多。"""
        k = 2 * max(2, round(font_size * 0.22)) + 1
        if k not in rooms:
            rooms[k] = box.interior.filter(ImageFilter.MinFilter(k))
        return rooms[k]

    def place(font: ImageFont.FreeTypeFont, font_size: int, lines: list[str]) -> Image.Image | None:
        pitch = round(font_size * pitch_ratio)
        heights = [font.getbbox(line) for line in lines]
        block_h = pitch * (len(lines) - 1) + (heights[-1][3] - heights[0][1])
        # 竖直方向照原来那几行字的中心；新的字更多时往框中间挪，别顶到框线
        ink_top = cy - block_h / 2
        ink_top = min(max(ink_top, 4), bh - 4 - block_h) if block_h <= bh - 8 else (bh - block_h) / 2
        top = round(ink_top) - heights[0][1]
        # 在大一圈的画布上排字：排到框外的字也看得见，才判断得出放不放得下
        m = max(bw, bh)
        canvas = Image.new("L", (bw + 2 * m, bh + 2 * m), 0)
        draw = ImageDraw.Draw(canvas)
        for i, line in enumerate(lines):
            x = left if box.rectangular else round(cx - font.getlength(line) / 2)
            draw.text((m + x, m + top + i * pitch), line, font=font, fill=255)
        limit = Image.new("L", canvas.size, 0)
        limit.paste(room(font_size), (m, m))
        return None if ImageChops.subtract(canvas, limit).getbbox() else canvas.crop((m, m, m + bw, m + bh))

    # 字明显多到框里装不下（按最小字号算面积都不够）：不用一个个试了
    if _units("".join(_split(text))) * smallest * smallest * pitch_ratio > box.interior.histogram()[255]:
        raise TextFixError("新的字在框里放不下：字太多了，或者框太小；改用 fix_comic_strip 修")
    layer = None
    sizes = sorted({max(smallest, round(size * f)) for f in (1, 0.96, 0.92, 0.88, 0.84, 0.8, 0.76)} | {smallest}, reverse=True)
    for font_size in sizes:
        font = _font(font_spec, font_size)
        # 方框按框宽折行；圆框按原来那几行字的宽度折，行数和形状接近原来的。
        # 写了分行的照分行排，某一行太长放不下时这一行里再折一次
        if explicit:  # 分好的行只在放不下框时再折
            width = (bw - left - 4) if box.rectangular else round(bw * 0.9)
        elif box.rectangular:
            width = bw - 2 * left
        elif len(bands) > 1:
            width = round(original_width * font_size / start_size * 1.04)
        else:  # 原来只有一行：新的字放得下就也排成一行
            width = round(bw * 0.75)
        if explicit:
            options = [_wrap(text, font, max(font_size, width))]
        else:  # 先只在标点后断行；放不下时多折一两行（每行差不多长），再考虑缩小字号
            options = []
            total = _units("".join(_split(text)))
            natural = len(_wrap(text, font, max(font_size, width)))
            for w in (max(font_size, width), *(math.ceil(total / n + 0.5) * font_size for n in (natural + 1, natural + 2))):
                for lines in (_phrases(text, font, w), _wrap(text, font, w)):
                    if lines not in options and all(font.getlength(line) <= max(w, width) for line in lines):
                        options.append(lines)
        for lines in options:
            layer = place(font, font_size, lines)
            if layer is not None:
                size = font_size
                break
        if layer is not None:
            break
    if layer is None:
        raise TextFixError("新的字在框里放不下：字太多了，或者框太小；改用 fix_comic_strip 修")
    region = image.crop(box.rect)
    region.paste(box.fill, (0, 0, bw, bh), box.interior)
    region.paste(box.color, (0, 0, bw, bh), layer)
    image.paste(region, box.rect[:2])
    out: dict = {"font_size": size, "lines": lines}
    if size < 0.9 * start_size:
        out["warning"] = f"字号从大约 {start_size} 缩到了 {size}，会比别的框小：把句子改短一点，或者用 fix_comic_strip 把框画大"
    return out
