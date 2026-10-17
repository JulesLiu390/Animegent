---
name: 版式草图
description: 用 Python + PIL 画条漫版式草图的约定：画布、格框、間白、编号，以及枠なし、断ち切り、重ねゴマ、はみ出し、コマまたぎ在草图上怎么标；代码环境、常用函数和四种版式结构的示例代码。用 draw_with_pil 手动画或修改版式草图之前读；draft_strip 会自动按它画。
version: 1.1.0
scopes: [comic]
---

# 版式草图的画法

版式草图只画格框、编号和标记，不画人物和文字。生成条漫时，它作为最后一张参考图交给生图模型，模型按它的格子形状和位置作画。每种手法用来表达什么情绪，见 panel-layout 技能；这里只讲怎么画出来。

## 基本约定
- **画布**：900×1600（9:16，和条漫同比例），白底；格框黑色，线宽 6 左右；页边距 20–30。
- **間白**：
  - 同一段里的格子之间留 12–16。窄缝把眼睛引向同一段的下一格。
  - 段与段之间留 28–36。宽缝表示这一段读完了。
  - 换场景、时间跳过去时，段距可以加宽到 50–80；要很长的停顿时，留一大片白場。
- **每段格数**：一段最多两格；放三格时，只能是没有字或字极短的小格。
- **编号**：每格中间写灰色 (170,170,170) 的大号编号（`ImageFont.load_default(size=120)`），重ねゴマ用小一号。编号就是阅读顺序，也是「画面指令」里的第几格。

## 特殊处理怎么标

| 手法 | 草图上的画法 |
|---|---|
| 枠なし | 不画格框，用灰色虚线框出范围，照常写编号 |
| 断ち切り | 不画格框，灰色虚线贴着图的边框出范围，照常写编号 |
| 重ねゴマ | 小格画在大格上面：先铺一圈白边，再画黑框；编号小一号 |
| はみ出し | 越出的那一块用灰色虚线框出来，框要跨过格框；框里的格框擦掉；写一个大写字母（A、B……），不写数字 |
| コマまたぎ | 人物占的范围用灰色虚线框出来，压在几格的格框上；框里的格框和間白擦掉；写一个大写字母 |
| 変形ゴマ | 斜切的格线、梯形 / 平行四边形（`draw.polygon`）、圆形（`draw.ellipse`）、圆角（`draw.rounded_rectangle`），都画成黑色格框 |
| 同ポジ、切开的一张画、跨間白的对白框 | 草图上照常画格子，在画面指令里写清楚 |

- **字母不是一格**：字母标的不是格子，是压在格子上的人物或物件。画面指令里要单独写一节，例如「### A｜跨格人物」，写清楚是谁、什么姿势、压在哪几格上、格框在哪里断开。
- **虚线只表示两种东西**：无框或断ち切り的格子，以及带字母的人物 / 物件。格子里面的文字带、局部区域都不画（生图模型会把它们当成格子），写进画面指令。
- **生成时不会画出来**：编号、字母和虚线都不会出现在生成的条漫里。

## 代码环境
- **沙箱**：代码在隔离的沙箱里运行（WebAssembly 里的 Python + Pillow），不能读写文件、不能联网，只能画图。
- **预置变量**：
  - `img`：白底 RGB 画布，W×H = 900×1600
  - `draw`：`img` 上的 ImageDraw
  - `W`、`H`、`Image`、`ImageDraw`、`ImageFont`、`math`
- **字体**：只有 `ImageFont.load_default(size=N)`，只能写英文字母和数字。
- **结果**：代码结束时的 `img` 就是草图。
- **坐标**：用变量算出来，保证間白均匀、编号在格子中间。

## 常用函数
完整的代码 = 下面这些函数 + 一段版式代码（例如后面的某个示例）。

```python
M, G, R = 25, 14, 32  # 页边距、同一段里的間白、段与段之间的間白
GRAY = (170, 170, 170)
big, small = ImageFont.load_default(size=120), ImageFont.load_default(size=80)


def label(text, x, y, font=big):
    draw.text((x, y), text, fill=GRAY, font=font, anchor="mm")


def box(n, x0, y0, x1, y1):
    """普通的格：黑框 + 编号。"""
    draw.rectangle([x0, y0, x1, y1], outline="black", width=6)
    label(str(n), (x0 + x1) / 2, (y0 + y1) / 2)


def dashed(x0, y0, x1, y1, step=30):
    """灰色虚线框：枠なし / 断ち切りの格，或者人物、物件占的范围。"""
    for x in range(x0, x1, step):
        draw.line([(x, y0), (min(x + 18, x1), y0)], fill=GRAY, width=3)
        draw.line([(x, y1), (min(x + 18, x1), y1)], fill=GRAY, width=3)
    for y in range(y0, y1, step):
        draw.line([(x0, y), (x0, min(y + 18, y1))], fill=GRAY, width=3)
        draw.line([(x1, y), (x1, min(y + 18, y1))], fill=GRAY, width=3)


def frameless(n, x0, y0, x1, y1):
    """枠なし / 断ち切り的格：没有黑框，虚线标范围，照常写编号。"""
    dashed(x0, y0, x1, y1)
    label(str(n), (x0 + x1) / 2, (y0 + y1) / 2)


def inset(n, x0, y0, x1, y1):
    """重ねゴマ：叠在大格上的小格，外圈留白边。"""
    draw.rectangle([x0 - 12, y0 - 12, x1 + 12, y1 + 12], fill="white")
    draw.rectangle([x0, y0, x1, y1], outline="black", width=6)
    label(str(n), (x0 + x1) / 2, (y0 + y1) / 2, small)


def figure(letter, x0, y0, x1, y1):
    """コマまたぎ / はみ出し：压在格框上的人物或物件。范围里的格框擦掉，虚线标范围，写字母。"""
    draw.rectangle([x0, y0, x1, y1], fill="white")
    dashed(x0, y0, x1, y1)
    label(letter, (x0 + x1) / 2, (y0 + y1) / 2)
```

## 示例

### A 叙述型
第一段左宽右窄两格；第 3 格是整宽的キメゴマ，约占页面三分之一；第 4、5 格逐渐变矮。

```python
top, bottom = M, 420
box(1, M, top, 560, bottom)
box(2, 560 + G, top, W - M, bottom)
top, bottom = bottom + R, bottom + R + 520
box(3, M, top, W - M, bottom)
top, bottom = bottom + R, bottom + R + 300
box(4, M, top, W - M, bottom)
box(5, M, bottom + R, W - M, H - M)
```

### B L 形
左边一个縦長ゴマ跨两段，右边上下两格；下面两段整宽。先读第 1 格，再读第 2、3 格。

```python
top, bottom = M, 760
box(1, M, top, 380, bottom)
mid = (top + bottom) // 2
box(2, 380 + G, top, W - M, mid - G // 2)
box(3, 380 + G, mid + G // 2, W - M, bottom)
top, bottom = bottom + R, bottom + R + 430
box(4, M, top, W - M, bottom)
box(5, M, bottom + R, W - M, H - M)
```

### C 断ち切り + 重ねゴマ
第 1 格断ち切り，画面一直延伸到图的上、左、右三边；第 2 格是叠在第 1 格右下角的小格；下面一段两格并排，最后整宽收尾。

```python
frameless(1, 0, 0, W - 1, 720)
inset(2, 560, 470, 860, 690)
top, bottom = 720 + R, 720 + R + 400
box(3, M, top, 440, bottom)
box(4, 440 + G, top, W - M, bottom)
box(5, M, bottom + R, W - M, H - M)
```

### D コマまたぎ
右边三格，左半边被一个不画框的全身人物 A 压住；最后一段整宽。读者先看人物 A，再读第 1、2、3 格。

```python
rows = [(M, 400), (400 + R, 790), (790 + R, 1180)]
for n, (y0, y1) in enumerate(rows, start=1):
    draw.rectangle([M, y0, W - M, y1], outline="black", width=6)
    label(str(n), 690, (y0 + y1) / 2)
figure("A", M, M, 430, 1180)
box(4, M, 1180 + R, W - M, H - M)
```
