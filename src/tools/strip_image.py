"""条漫成图的图片处理（只用 PIL）：找格子、叠坐标方格、画修图标记、把改好的区域贴回原图。

- 找格子：条漫是白色格缝、黑色格框。整行几乎全白的是行与行之间的缝，在每一行里再按整列全白的缝切开。
  格子里的白色条带两边有黑框，不会被当成格缝。顺序是从上到下、同一行从左到右，和阅读顺序一致。
- 坐标方格：6 列（A–F）× 10 行（1–10）盖住整张图，检查和修图都用它说位置（例如 C4、C4:D6）。
"""

from __future__ import annotations

import string
from collections.abc import Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

Rect = tuple[int, int, int, int]  # (x0, y0, x1, y1)，x1 / y1 不含

GRID_COLS = 6
GRID_ROWS = 10
_WHITE = 235  # 灰度 ≥ 这个值算白
_GUTTER = 0.995  # 一行 / 一列里白色占比 ≥ 这个值算格缝


def _values(img: Image.Image) -> list[float]:
    getter = getattr(img, "get_flattened_data", None) or img.getdata
    return [v / 255 for v in getter()]


def _runs(flags: Sequence[bool], min_len: int) -> list[tuple[int, int]]:
    out, start = [], None
    for i, flag in enumerate([*flags, False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    return out


def find_panels(img: Image.Image) -> list[Rect]:
    """按白色格缝找出每一格（含格框），按阅读顺序排列。无框出血的格子会和相邻的格子连在一起。"""
    binary = img.convert("L").point(lambda v: 255 if v >= _WHITE else 0)
    w, h = binary.size
    rows = _values(binary.resize((1, h), Image.Resampling.BOX))
    rects: list[Rect] = []
    for y0, y1 in _runs([r < _GUTTER for r in rows], max(8, h // 100)):
        cols = _values(binary.crop((0, y0, w, y1)).resize((w, 1), Image.Resampling.BOX))
        for x0, x1 in _runs([c < _GUTTER for c in cols], max(8, w // 60)):
            rects.append((x0, y0, x1, y1))
    return rects


def _cell_bounds(size: tuple[int, int], col: int, row: int) -> Rect:
    w, h = size
    return (col * w // GRID_COLS, row * h // GRID_ROWS, (col + 1) * w // GRID_COLS, (row + 1) * h // GRID_ROWS)


def _parse_cell(cell: str) -> tuple[int, int]:
    cell = cell.strip().upper()
    if len(cell) < 2 or cell[0] not in string.ascii_uppercase[:GRID_COLS] or not cell[1:].isdigit():
        raise ValueError(f"方格坐标「{cell}」不对：列是 A–{string.ascii_uppercase[GRID_COLS - 1]}，行是 1–{GRID_ROWS}，例如 C4")
    col, row = ord(cell[0]) - ord("A"), int(cell[1:]) - 1
    if not 0 <= row < GRID_ROWS:
        raise ValueError(f"方格坐标「{cell}」的行号超出 1–{GRID_ROWS}")
    return col, row


def area_rect(area: str, size: tuple[int, int]) -> Rect:
    """方格坐标（C4 或 C4:D6）→ 像素矩形。"""
    parts = [p for p in area.replace("：", ":").replace("-", ":").replace("–", ":").split(":") if p.strip()]
    if not parts or len(parts) > 2:
        raise ValueError(f"方格坐标「{area}」不对，写成 C4 或 C4:D6")
    (c0, r0), (c1, r1) = _parse_cell(parts[0]), _parse_cell(parts[-1])
    a, b = _cell_bounds(size, min(c0, c1), min(r0, r1)), _cell_bounds(size, max(c0, c1), max(r0, r1))
    return (a[0], a[1], b[2], b[3])


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def draw_grid(img: Image.Image) -> Image.Image:
    """叠一层半透明的坐标方格（A–F 列、1–10 行），每格左上角写坐标。"""
    base = img.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    w = base.width
    line = max(2, w // 400)
    font = _font(max(14, w // 40))
    for col in range(GRID_COLS):
        for row in range(GRID_ROWS):
            x0, y0, x1, y1 = _cell_bounds(base.size, col, row)
            draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(0, 160, 255, 150), width=line)
            label = f"{string.ascii_uppercase[col]}{row + 1}"
            box = draw.textbbox((x0 + 6, y0 + 4), label, font=font)
            draw.rectangle([box[0] - 3, box[1] - 2, box[2] + 3, box[3] + 2], fill=(255, 255, 255, 190))
            draw.text((x0 + 6, y0 + 4), label, fill=(0, 110, 200, 255), font=font)
    return Image.alpha_composite(base, layer).convert("RGB")


def mark(img: Image.Image, boxes: Sequence[tuple[Rect, str]]) -> Image.Image:
    """坐标方格 + 每处要修的地方画红框、标上编号。"""
    marked = draw_grid(img)
    draw = ImageDraw.Draw(marked)
    w = marked.width
    width = max(4, w // 180)
    font = _font(max(20, w // 22))
    for (x0, y0, x1, y1), label in boxes:
        draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(235, 20, 40), width=width)
        tag = draw.textbbox((x0 + width + 4, y0 + width + 2), label, font=font)
        draw.rectangle([tag[0] - 6, tag[1] - 4, tag[2] + 6, tag[3] + 4], fill=(235, 20, 40))
        draw.text((x0 + width + 4, y0 + width + 2), label, fill="white", font=font)
    return marked


def panel_at(panels: Sequence[Rect], rect: Rect) -> Rect | None:
    """rect 的中心落在哪一格。"""
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    return next((p for p in panels if p[0] <= cx < p[2] and p[1] <= cy < p[3]), None)


def inset(rect: Rect, amount: int) -> Rect:
    x0, y0, x1, y1 = rect
    return (x0 + amount, y0 + amount, max(x0 + amount + 1, x1 - amount), max(y0 + amount + 1, y1 - amount))


def _intersect(a: Rect, b: Rect) -> Rect | None:
    r = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return r if r[0] < r[2] and r[1] < r[3] else None


def composite(original: Image.Image, edited: Image.Image, boxes: Sequence[Rect], *, clips: Sequence[Rect | None] | None = None,
              margin: float = 0.02, feather: float = 0.01) -> Image.Image:
    """只把 edited 里 boxes 范围（稍微放大、边缘羽化）的部分贴回 original，其他像素保持原样。

    clips（每个 box 对应一个，可以是 None）是它所在那一格的内部：贴回的范围不超出这一格，格框和相邻的格保持原样。
    """
    base = original.convert("RGB")
    patch = edited.convert("RGB").resize(base.size, Image.Resampling.LANCZOS) if edited.size != base.size else edited.convert("RGB")
    w, h = base.size
    pad, blur = round(w * margin), max(1, round(w * feather))
    clips = list(clips or [None] * len(boxes))
    mask = Image.new("L", base.size, 0)
    limit = Image.new("L", base.size, 0)
    draw, draw_limit = ImageDraw.Draw(mask), ImageDraw.Draw(limit)
    for (x0, y0, x1, y1), clip in zip(boxes, clips, strict=True):
        region: Rect | None = (max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad))
        if clip:
            region = _intersect(region, clip)
        if region:
            draw.rectangle([region[0], region[1], region[2] - 1, region[3] - 1], fill=255)
        draw_limit.rectangle(list(clip or (0, 0, w, h)), fill=255)
    soft = ImageChops.multiply(mask.filter(ImageFilter.GaussianBlur(blur)), limit)
    return Image.composite(patch, base, soft)


def aspect_close(a: tuple[int, int], b: tuple[int, int], tolerance: float = 0.02) -> bool:
    return abs(a[0] / a[1] - b[0] / b[1]) <= tolerance * (b[0] / b[1])
