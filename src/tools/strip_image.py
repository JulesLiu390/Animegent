"""条漫成图的图片处理（只用 PIL）：找格子、叠坐标方格、画修图标记、找出改了哪里、把改好的区域贴回原图。

- 找格子：条漫是白色格缝、黑色格框。整行几乎全白的是行与行之间的缝，在每一行里再按整列全白的缝切开。
  格子里的白色条带两边有黑框，不会被当成格缝。顺序是从上到下、同一行从左到右，和阅读顺序一致。
- 坐标方格：6 列（A–F）× 10 行（1–10）盖住整张图，检查和修图都用它说位置（例如 C4、C4:D6）。
- 改了哪里：生图模型每次都把整张图重画一遍，线条会挪一两个像素。缩小后再比较、去掉细碎的点，
  剩下的成片变化才是真的改动（换了颜色、挪了手）。贴回时顺着这些改动走，红框只框住一部分也不会留下半截旧图。
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


def panels_in(panels: Sequence[Rect], rect: Rect, share: float = 0.2) -> list[Rect]:
    """rect 落在哪几格：一个方格坐标可能跨过格缝，落在上下两格里。只蹭到一点边的格子不算。"""
    area = max(1, (rect[2] - rect[0]) * (rect[3] - rect[1]))
    out = []
    for p in panels:
        r = _intersect(p, rect)
        if r and (r[2] - r[0]) * (r[3] - r[1]) >= share * area:
            out.append(p)
    return out


def _matched(edited: Image.Image, size: tuple[int, int]) -> Image.Image:
    edited = edited.convert("RGB")
    return edited.resize(size, Image.Resampling.LANCZOS) if edited.size != size else edited


class Changes:
    """original 和 edited 之间成片的变化，在缩小的图上算（scale 是缩小的倍数）。"""

    THRESHOLD = 40  # 缩小后某个颜色通道差这么多才算变了

    def __init__(self, original: Image.Image, edited: Image.Image):
        w, h = original.size
        self.size = original.size
        self.scale = max(1, w // 240)
        small = (max(1, w // self.scale), max(1, h // self.scale))
        a = original.convert("RGB").resize(small, Image.Resampling.BOX)
        b = _matched(edited, original.size).resize(small, Image.Resampling.BOX)
        diff = ImageChops.difference(a, b).split()
        strongest = ImageChops.lighter(ImageChops.lighter(diff[0], diff[1]), diff[2])
        # strong：缩小后差得多的点（量一处改了多少用）；mask：再去掉细碎的点，剩下成片的变化（贴回时顺着它走）
        self.strong = strongest.point(lambda v: 255 if v >= self.THRESHOLD else 0)
        self.mask = self.strong.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))

    def _small(self, rect: Rect) -> Rect:
        s = self.scale
        return (rect[0] // s, rect[1] // s, max(rect[0] // s + 1, -(-rect[2] // s)), max(rect[1] // s + 1, -(-rect[3] // s)))

    def _rects(self, rects: Sequence[Rect]) -> Image.Image:
        out = Image.new("L", self.mask.size, 0)
        draw = ImageDraw.Draw(out)
        for r in rects:
            x0, y0, x1, y1 = self._small(r)
            draw.rectangle([x0, y0, x1 - 1, y1 - 1], fill=255)
        return out

    def fraction(self, rect: Rect) -> float:
        """rect 里有多大比例变了。"""
        crop = self.strong.crop(self._small(rect))
        return crop.histogram()[255] / max(1, crop.width * crop.height)

    def noise(self, rects: Sequence[Rect]) -> float:
        """rects 附近以外变了的比例：模型重画整张图带来的底噪，用来判断一处是真的改了还是只是重画了一遍。"""
        away = ImageChops.invert(self._rects(rects).filter(ImageFilter.MaxFilter(9)))
        total = away.histogram()[255]
        return ImageChops.multiply(self.strong, away).histogram()[255] / total if total else 0.0

    GROWTH = 4.0  # 连着的那片改动最多是框的几倍大；再大多半是整张偏了色，不是这一处的改动

    def grown(self, seed: Rect, within: Sequence[Rect]) -> Image.Image:
        """和 seed 范围连在一起的那片变化（不超出 within 这几格），缩小图上的蒙版；大得不像这一处的改动时为空。"""
        allowed = ImageChops.multiply(self.mask, self._rects(within))
        region = ImageChops.multiply(allowed, self._rects([seed]))
        x0, y0, x1, y1 = self._small(seed)
        limit = self.GROWTH * (x1 - x0) * (y1 - y0)
        for _ in range(max(self.mask.size)):
            bigger = ImageChops.multiply(region.filter(ImageFilter.MaxFilter(5)), allowed)
            if bigger.histogram()[255] > limit:
                return Image.new("L", self.mask.size, 0)
            if ImageChops.difference(bigger, region).getbbox() is None:
                break
            region = bigger
        return region

    def outside(self, rects: Sequence[Rect], panels: Sequence[Rect], min_fraction: float = 0.02) -> list[int]:
        """rects（及其附近）以外、哪几格（从 1 数）有成片的变化：模型可能把改动画到了框外。"""
        covered = self._rects(rects).filter(ImageFilter.MaxFilter(9))
        rest = ImageChops.subtract(self.mask, covered)
        out = []
        for i, p in enumerate(panels, start=1):
            crop = rest.crop(self._small(p))
            if crop.histogram()[255] / max(1, crop.width * crop.height) >= min_fraction:
                out.append(i)
        return out


def composite(original: Image.Image, edited: Image.Image, boxes: Sequence[Rect], *,
              clips: Sequence[Rect | Sequence[Rect] | None] | None = None, changes: Changes | None = None,
              margin: float = 0.02, feather: float = 0.01) -> Image.Image:
    """只把 edited 里 boxes 范围（稍微放大、边缘羽化）的部分贴回 original，其他像素保持原样。

    clips（每个 box 对应一个：一格或几格的内部，可以是 None）：贴回的范围不超出这几格，格框和别的格保持原样。
    changes：给了的话，和红框连在一起的那片变化也一起贴回（框只框住了半只手时，整只手都换成新的）。
    贴到格框边上时不羽化：边上由格框挡着，羽化反而会让新旧两张图叠出重影。
    """
    base = original.convert("RGB")
    patch = _matched(edited, base.size)
    w, h = base.size
    pad, blur = round(w * margin), max(1, round(w * feather))
    clips = list(clips or [None] * len(boxes))
    soft = Image.new("L", base.size, 0)
    for (x0, y0, x1, y1), clip in zip(boxes, clips, strict=True):
        within: list[Rect] = [clip] if clip and isinstance(clip[0], int) else list(clip or [(0, 0, w, h)])  # type: ignore[arg-type]
        region = (max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad))
        # 先画不受格子限制的范围、羽化，最后再按格子硬切：格框边上保持全强度
        mask = Image.new("L", base.size, 0)
        ImageDraw.Draw(mask).rectangle([region[0], region[1], region[2] - 1, region[3] - 1], fill=255)
        if changes is not None:
            grown = changes.grown(region, within)
            if grown.getbbox():
                reach = 2 * (2 * blur // changes.scale) + 1  # 往外放一圈再羽化：羽化落在没变的地方
                grown = grown.filter(ImageFilter.MaxFilter(max(3, reach))).resize(base.size, Image.Resampling.NEAREST)
                mask = ImageChops.lighter(mask, grown)
        limit = Image.new("L", base.size, 0)
        draw_limit = ImageDraw.Draw(limit)
        for c in within:
            draw_limit.rectangle([c[0], c[1], c[2] - 1, c[3] - 1], fill=255)
        soft = ImageChops.lighter(soft, ImageChops.multiply(mask.filter(ImageFilter.GaussianBlur(blur)), limit))
    return Image.composite(patch, base, soft)


def aspect_close(a: tuple[int, int], b: tuple[int, int], tolerance: float = 0.02) -> bool:
    return abs(a[0] / a[1] - b[0] / b[1]) <= tolerance * (b[0] / b[1])
